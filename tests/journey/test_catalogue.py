"""The Email journey's catalogue (D-057) against the renderer it describes,
the checks an edit must pass, and edits reaching the rendered emails."""

from __future__ import annotations

import itertools
from datetime import UTC, date, datetime, timedelta

import pytest

from lge.journey import catalogue
from lge.journey.build import build_journey
from lge.journey.model import Contact, Firm, JourneyEdits, JourneyLead, Signal
from lge.journey.render import COPY_ROOT, load_template

AT = datetime(2026, 9, 19, tzinfo=UTC)

_TIERS = {
    "1A": ("personal_injury", "contingency"),
    "1B": ("immigration", "flat"),
    "2": ("employment", "fee_shifting"),
    "3": ("bankruptcy", "flat"),
    "4_NONBILLABLE": ("estate", "hourly"),
}
_ROLE = {"title": "Paralegal", "canonical_role": "paralegal"}
_INTAKE = {"title": "Intake", "canonical_role": "intake"}
_PAINS: dict[str, tuple[str, dict, int]] = {
    "open": ("job_posting_open", _ROLE, 0),
    "repost": ("job_posting_open", _ROLE, 1),
    "two": ("multi_opening", {"roles": [_ROLE, _INTAKE]}, 0),
    "tort": ("mass_tort_campaign", {"tort": "Camp Lejeune"}, 0),
    "reviews": ("review_unreturned_call", {"reviews": 3}, 0),
    "system": ("cms_implemented", {"cms": "filevine"}, 0),
}


def _lead(tier="1A", pain="open", cms="filevine", band="SEQUENCE") -> JourneyLead:
    practice, fee_model = _TIERS[tier]
    kind, evidence, reposts = _PAINS[pain]
    return JourneyLead(
        lead_id="l1", band=band,
        firm=Firm("f1", "Harbor & Vale Law", "Atlanta", "GA", tier, fee_model, practice, cms),
        contact=Contact("c1", "Dana Whitfield", "Managing Partner", "owner"),
        signal=Signal(1, kind, AT - timedelta(days=24), AT, None, reposts, evidence),
        repost_first_seen=date(2026, 8, 10) if reposts else None,
        at=AT,
    )


def test_every_copy_file_is_listed_once_and_every_listing_exists():
    on_disk = sorted(p.relative_to(COPY_ROOT).as_posix() for p in COPY_ROOT.rglob("*.md"))
    listed = sorted(t.path for t in catalogue.TEMPLATES)
    assert listed == on_disk
    assert len({t.id for t in catalogue.TEMPLATES}) == len(catalogue.TEMPLATES)


def test_every_email_has_a_step_and_every_step_an_email():
    assert sorted(catalogue.STEPS) == list(range(1, 10))
    for step in catalogue.STEPS:
        assert any(t.step == step and t.kind == "email" for t in catalogue.TEMPLATES)


def test_every_file_the_renderer_uses_is_catalogued_under_the_email_it_rendered():
    seen: set[str] = set()
    for tier, pain, cms, band in itertools.product(
        _TIERS, _PAINS, ("filevine", None), ("SEQUENCE", "NURTURE")
    ):
        result = build_journey(_lead(tier, pain, cms, band))
        for touch in result.touches:
            assert touch.templates, f"touch {touch.step} names no copy file"
            first = catalogue.BY_PATH[touch.templates[0]]
            assert first.step == touch.step and first.kind == "email"
            for path in touch.templates[1:]:
                assert catalogue.BY_PATH[path].kind == "paragraph"
            seen.update(touch.templates)
    # Every catalogued file is reachable from some firm the screen can show.
    assert seen == {t.path for t in catalogue.TEMPLATES}


def test_the_days_come_from_sequences_yml():
    days = {t.step: t.day for t in build_journey(_lead()).touches}
    assert days == {s: d for s, d in catalogue.config_days().items() if s in days}
    assert catalogue.config_days() == {1: 0, 2: 3, 3: 7, 4: 10, 5: 14, 6: 18, 7: 21, 8: 25, 9: 28}


def test_edited_wording_and_days_reach_the_rendered_emails():
    subject, body = load_template("touch3/contingency.md")
    edits = JourneyEdits(
        copy={"touch3/contingency.md": ("the hours, {first_name}", body + "\n\nAlso this.")},
        days={2: 1, 3: 2},
    )
    touches = {t.step: t for t in build_journey(_lead(), edits).touches}
    assert touches[3].subject == "the hours, Dana"
    # under the edited copy come the offer and the call to action (D-070),
    # then the signature the renderer appends to every email (D-060)
    body3 = touches[3].body
    assert "\n\nAlso this.\n\n" in body3
    assert body3.index("Also this.") < body3.index(touches[3].usp) < body3.index(touches[3].cta)
    assert body3.index(touches[3].cta) < body3.index("\n\nBest regards,\n")
    assert (touches[2].day, touches[3].day, touches[4].day) == (1, 2, 10)
    assert subject != touches[3].subject  # the file itself is untouched
    assert load_template("touch3/contingency.md") == (subject, body)


def test_an_edited_paragraph_reaches_the_email_it_is_set_into():
    edits = JourneyEdits(copy={"touch1/_middle_1a.md": (None, "One person, inside {cms}.")})
    touch1 = build_journey(_lead(), edits).touches[0]
    assert "One person, inside Filevine." in touch1.body
    assert touch1.templates == ("touch1/1a.md", "touch1/_middle_1a.md")


def test_nurture_keeps_half_the_pace_of_edited_days():
    edits = JourneyEdits(days={3: 5, 9: 20})
    days = {t.step: t.day for t in build_journey(_lead(band="NURTURE"), edits).touches}
    assert days == {1: 0, 3: 10, 9: 40}


# ---------------------------------------------------------------------------
# The checks an edit must pass
# ---------------------------------------------------------------------------

def _email(template_id: str):
    return catalogue.BY_ID[template_id]


def test_the_original_wording_passes_every_check():
    for t in catalogue.TEMPLATES:
        subject, body = load_template(t.path)
        assert catalogue.copy_problems(t, subject, body) == [], t.id


def test_fill_ins_are_those_the_original_used_plus_name_and_firm():
    assert catalogue.allowed_fill_ins(_email("1-open-role")) == [
        "first_name", "firm_name", "role", "posted_date",
    ]  # the closing line's {cms} lives in the paragraph, not this file
    assert catalogue.allowed_fill_ins(_email("7")) == ["first_name", "firm_name"]


@pytest.mark.parametrize(
    ("template_id", "subject", "body", "problem"),
    [
        ("7", "", "{first_name} — hello.", "Add a subject line."),
        ("7", "one\ntwo", "{first_name} — hello.", "Keep the subject on one line."),
        ("7", "right person?", "   ", "The email can't be empty."),
        ("7", "right person?", "We can replace your paralegal.", "“replace”"),
        ("7", "right person?", "Cheaper Than Hiring, {first_name}.", "“cheaper than hiring”"),
        ("7", "right person?", "Hi {city}.", "{city} can't be filled in here."),
        ("7", "right person?", "Hi {first name}.", "A { or } that is not part of a fill-in"),
        ("1-open-role", "your {role} opening", "No paragraph here.", "Keep {middle_paragraph}"),
        ("1-open-role", "your {role} opening", "{middle_paragraph} {middle_paragraph}",
         "Keep {middle_paragraph}"),
        ("1-paragraph-pi", "a subject", "We place people.", "A paragraph has no subject line."),
        ("1-paragraph-pi", None, "Goes in {middle_paragraph}.", "{middle_paragraph} can't be"),
    ],
)
def test_an_edit_is_refused_with_the_reason(template_id, subject, body, problem):
    problems = catalogue.copy_problems(_email(template_id), subject, body)
    assert any(problem in p for p in problems), problems


def test_a_new_wording_with_allowed_fill_ins_passes():
    assert catalogue.copy_problems(
        _email("1-open-role"),
        "{firm_name}: the {role} role",
        "{first_name}, since {posted_date}.\n\n{middle_paragraph}\n\nA call?",
    ) == []


def test_days_must_rise_and_stay_in_range():
    assert catalogue.day_problems({2: 1, 3: 2, 4: 3}) == []
    assert catalogue.day_problems({1: 2}) == ["Email 1 always goes on Day 1."]
    assert catalogue.day_problems({2: 0}) == ["Email 2 must go between Day 2 and Day 91."]
    assert catalogue.day_problems({2: 91}) == ["Email 2 must go between Day 2 and Day 91."]
    assert catalogue.day_problems({3: 3}) == [
        "Email 3 must come after email 2, which goes on Day 4."
    ]
    assert catalogue.day_problems({12: 3}) == ["There is no email 12."]
