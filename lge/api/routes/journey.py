"""The Email journey screen (D-057).

GET /api/journey: the nine emails, the day each one goes, every template's
wording (as edited and as written) and who gets which track. PUT/DELETE
/api/journey/templates/{id} changes or restores one template's wording for
every lead; PUT/DELETE /api/journey/days does the same for the schedule.
GET /api/journey/example renders the journey for an invented firm through
the engine's own renderer, so the screen can show real emails before any
lead is ready.

The engine drafts; nothing here sends. Edits sit beside the originals
(sql/102_journey_edits.sql) and every renderer reads them back through
lge.export.list.fetch_journey_edits.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import psycopg
from fastapi import APIRouter, Query, Request

from lge.api.deps import ConnDep
from lge.api.errors import api_error, not_found
from lge.api.gate import actor_of
from lge.api.models import (
    JourneyCopyEdit,
    JourneyDaysEdit,
    JourneyExample,
    JourneyFillIn,
    JourneyOption,
    JourneyPain,
    JourneyResponse,
    JourneyStep,
    JourneyTemplate,
    JourneyTier,
    JourneyTrack,
    JourneyTrackBand,
)
from lge.api.routes.leads import drafts_from_result
from lge.export.list import fetch_journey_edits
from lge.journey import catalogue
from lge.journey.build import build_journey
from lge.journey.model import Contact, Firm, JourneyEdits, JourneyLead, Signal
from lge.journey.render import load_template, sender_missing, signature
from lge.journey.select import load_config
from lge.journey.tokens import humanize_practice

router = APIRouter(prefix="/api", tags=["journey"])

# The example firm, one per tier: (label, practice, fee model, the role it posted).
_EXAMPLE_TIERS: dict[str, tuple[str, str, str, str]] = {
    "1A": ("Personal injury, on contingency (tier 1A)", "personal_injury", "contingency",
           "Paralegal"),
    "1B": ("Immigration, on flat fees (tier 1B)", "immigration", "flat", "Legal Assistant"),
    "2": ("Employment, where the other side pays the fees (tier 2)", "employment",
          "fee_shifting", "Case Manager"),
    "3": ("Bankruptcy, flat fees at volume (tier 3)", "bankruptcy", "flat", "Legal Assistant"),
    "4_NONBILLABLE": ("Estate planning, billed by the hour (tier 4)", "estate", "hourly",
                      "Bookkeeper"),
}
_EXAMPLE_PAINS: dict[str, str] = {
    "open_role": "An open job post",
    "reposted_role": "A job post put up again",
    "two_roles": "Two roles posted at once",
    "mass_tort": "A mass tort campaign",
    "reviews": "Reviews about calls not returned",
    "new_system": "A newly adopted case system",
}


def _day_word(days_after_first: int) -> str:
    return f"Day {days_after_first + 1}"


def _and_list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _tracks(days: dict[int, int]) -> list[JourneyTrack]:
    rules = load_config()["band_rules"]
    sequence = [int(s) for s in rules["SEQUENCE"]["touches"]]
    nurture = [int(s) for s in rules["NURTURE"]["touches_with_signal"]]
    pace = int(rules["NURTURE"]["day_multiplier"])
    return [
        JourneyTrack(
            band="SEQUENCE", label="Sequence", steps=sequence, pace=1,
            description=(
                f"Up to nine emails, {_day_word(0)} to {_day_word(days[sequence[-1]])}. An email "
                "with nothing true to say to a firm is left out, never padded."
            ),
        ),
        JourneyTrack(
            band="NURTURE", label="Nurture", steps=nurture, pace=pace,
            description=(
                f"Emails {_and_list([str(s) for s in nurture])} at half the pace: "
                f"{_and_list([_day_word(days[s] * pace) for s in nurture])}. "
                "With no pain on record the first is left out."
            ),
        ),
        JourneyTrack(
            band="STRIKE", label="Strike", steps=[], pace=1,
            description=(
                "Written by hand, the same day. A need nobody else has seen is worth a "
                "person's own words, so the engine drafts nothing."
            ),
        ),
        JourneyTrack(band="HOLD", label="Hold", steps=[], pace=1, description="Not contacted."),
    ]


def _edited_at(conn: psycopg.Connection) -> dict[str, datetime]:
    with conn.cursor() as cur:
        cur.execute("SELECT template, edited_at FROM journey_copy_edit")
        return {row["template"]: row["edited_at"] for row in cur.fetchall()}


def _template_out(
    t: catalogue.CatalogueTemplate, edits: JourneyEdits, edited_at: dict[str, datetime]
) -> JourneyTemplate:
    original_subject, original_body = load_template(t.path)
    subject, body = edits.copy.get(t.path, (original_subject, original_body))
    email = t.kind == "email"
    return JourneyTemplate(
        id=t.id, step=t.step, kind=t.kind, used_when=t.used_when,
        subject=subject if email else None, body=body,
        original_subject=original_subject if email else None, original_body=original_body,
        edited_at=edited_at.get(t.path), fill_ins=catalogue.allowed_fill_ins(t), keeps=t.keeps,
    )


def _journey(conn: psycopg.Connection) -> JourneyResponse:
    edits = fetch_journey_edits(conn)
    edited_at = _edited_at(conn)
    days = catalogue.schedule(edits.days)
    original_days = catalogue.config_days()
    steps = [
        JourneyStep(
            step=step, day=days[step], original_day=original_days[step],
            title=info.title, purpose=info.purpose, varies_by=info.varies_by,
            templates=[
                _template_out(t, edits, edited_at) for t in catalogue.TEMPLATES if t.step == step
            ],
        )
        for step, info in catalogue.STEPS.items()
    ]
    return JourneyResponse(
        steps=steps,
        tracks=_tracks(days),
        fill_ins=[
            JourneyFillIn(token=token, label=label, meaning=meaning)
            for token, (label, meaning) in catalogue.FILL_INS.items()
        ],
        banned_phrases=list(load_config()["banned_phrases"]),
        max_day=catalogue.MAX_DAY,
        signature=signature(),
        sender_missing=sender_missing(),
        tiers=[JourneyOption(value=k, label=v[0]) for k, v in _EXAMPLE_TIERS.items()],
        pains=[JourneyOption(value=k, label=v) for k, v in _EXAMPLE_PAINS.items()],
    )


@router.get("/journey", response_model=JourneyResponse)
def get_journey(conn: ConnDep) -> JourneyResponse:
    return _journey(conn)


def _catalogued(template_id: str) -> catalogue.CatalogueTemplate:
    template = catalogue.BY_ID.get(template_id)
    if template is None:
        raise not_found("There is no such email.", "Reload the Email journey screen.")
    return template


@router.put("/journey/templates/{template_id}", response_model=JourneyTemplate)
def put_template(
    template_id: str, body: JourneyCopyEdit, conn: ConnDep, request: Request
) -> JourneyTemplate:
    """New wording for one template, for every lead from now on. Saving the
    original wording back is the same as restoring it."""
    template = _catalogued(template_id)
    email = template.kind == "email"
    subject = (body.subject or "").strip() if email else None
    text = body.body.replace("\r\n", "\n").strip("\n")
    problems = catalogue.copy_problems(template, subject, text)
    if problems:
        raise api_error(
            422, "invalid_copy", " ".join(problems), "Change the wording and save again."
        )

    original_subject, original_body = load_template(template.path)
    with conn.cursor() as cur:
        if subject == (original_subject if email else None) and text == original_body:
            cur.execute("DELETE FROM journey_copy_edit WHERE template = %s", (template.path,))
        else:
            cur.execute(
                "INSERT INTO journey_copy_edit (template, subject, body, edited_at, edited_by) "
                "VALUES (%s, %s, %s, now(), %s) "
                "ON CONFLICT (template) DO UPDATE SET subject = EXCLUDED.subject, "
                "body = EXCLUDED.body, edited_at = EXCLUDED.edited_at, "
                "edited_by = EXCLUDED.edited_by",
                (template.path, subject, text, actor_of(request)),
            )
    return _template_out(template, fetch_journey_edits(conn), _edited_at(conn))


@router.delete("/journey/templates/{template_id}", response_model=JourneyTemplate)
def restore_template(template_id: str, conn: ConnDep) -> JourneyTemplate:
    """Back to the wording in journey/copy/."""
    template = _catalogued(template_id)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM journey_copy_edit WHERE template = %s", (template.path,))
    return _template_out(template, fetch_journey_edits(conn), _edited_at(conn))


@router.put("/journey/days", response_model=JourneyResponse)
def put_days(body: JourneyDaysEdit, conn: ConnDep, request: Request) -> JourneyResponse:
    """The whole schedule at once: an email left out of `days` goes back to
    its original day, so the screen always sends every email it shows."""
    days = {d.step: d.day for d in body.days}
    if len(days) != len(body.days):
        raise api_error(
            422, "invalid_days", "Each email can have one day.", "Send each email once."
        )
    problems = catalogue.day_problems(days)
    if problems:
        raise api_error(422, "invalid_days", " ".join(problems), "Change the days and save again.")

    original = catalogue.config_days()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM journey_day_edit")
        for step, day in catalogue.schedule(days).items():
            if step != 1 and day != original[step]:
                cur.execute(
                    "INSERT INTO journey_day_edit (step, day, edited_at, edited_by) "
                    "VALUES (%s, %s, now(), %s)",
                    (step, day, actor_of(request)),
                )
    return _journey(conn)


@router.delete("/journey/days", response_model=JourneyResponse)
def restore_days(conn: ConnDep) -> JourneyResponse:
    """Back to the days in journey/sequences.yml."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM journey_day_edit")
    return _journey(conn)


def _example_signal(pain: str, role: str, at: datetime) -> tuple[Signal, date | None]:
    """The pain an invented firm shows, shaped as the signal the engine would store."""
    role_evidence = {"title": role, "canonical_role": role.lower().replace(" ", "_")}
    first_seen = at - timedelta(days=24)
    kind, evidence, reposts, repost_seen = "job_posting_open", dict(role_evidence), 0, None
    if pain == "reposted_role":
        first_seen = at - timedelta(days=70)
        reposts, repost_seen = 1, (at - timedelta(days=40)).date()
    elif pain == "two_roles":
        kind = "multi_opening"
        evidence = {"roles": [
            role_evidence, {"title": "Intake Specialist", "canonical_role": "intake_specialist"},
        ]}
    elif pain == "mass_tort":
        kind, evidence = "mass_tort_campaign", {"tort": "Camp Lejeune"}
    elif pain == "reviews":
        kind, evidence = "review_unreturned_call", {"reviews": 3}
    elif pain == "new_system":
        kind, evidence = "cms_implemented", {"cms": "filevine"}
    signal = Signal(
        id=0, kind=kind, first_seen=first_seen, last_seen=at - timedelta(days=1),
        closed_at=None, repost_count=reposts, evidence=evidence,
    )
    return signal, repost_seen


@router.get("/journey/example", response_model=JourneyExample)
def get_example(
    conn: ConnDep,
    tier: Annotated[JourneyTier, Query()] = "1A",
    pain: Annotated[JourneyPain, Query()] = "open_role",
    system: bool = True,
    band: Annotated[JourneyTrackBand, Query()] = "SEQUENCE",
) -> JourneyExample:
    """What an invented firm would be sent, rendered by build_journey with the
    screen's edits -- the same path a real lead's drafts take."""
    at = datetime.now(UTC)
    _label, practice, fee_model, role = _EXAMPLE_TIERS[tier]
    firm = Firm(
        id="example", canonical_name="Harbor & Vale Law", city="Atlanta", state="GA",
        tier=tier, fee_model=fee_model, primary_practice=practice,
        cms_detected="filevine" if system else None,
    )
    contact = Contact(
        id="example", full_name="Dana Whitfield", title="Managing Partner", role="owner"
    )
    signal, repost_seen = _example_signal(pain, role, at)
    lead = JourneyLead(
        lead_id="example", band=band, firm=firm, contact=contact, signal=signal,
        repost_first_seen=repost_seen, at=at,
    )
    result = build_journey(lead, fetch_journey_edits(conn))
    where = "on Filevine" if system else "its case system not known"
    return JourneyExample(
        firm=f"An invented {humanize_practice(practice)} firm in Atlanta, {where}",
        person="Dana Whitfield, managing partner",
        tier=tier, pain=pain, system=system, band=band,
        drafts=drafts_from_result(band, result, bool(signal.evidence)),
    )
