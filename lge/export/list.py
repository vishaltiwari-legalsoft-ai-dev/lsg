"""build_list -- the export plane's one component. Reads qualified leads,
applies the list-hygiene filters (PLAN.md "The one list hygiene rule that
stays" + this task's list-hygiene bullets) AT BUILD TIME, renders each
SEQUENCE/NURTURE lead's outreach journey via `lge.journey.build`, and writes
everything under `data/out/`:

  leads_ranked.csv  -- STRIKE + SEQUENCE + NURTURE, grade A, journey-eligible
  strike.csv        -- STRIKE band only, for a human (not rendered)
  phone_list.csv    -- grade B, never emailed
  drafts/<slug>.md  -- the rendered 9-touch (or reduced NURTURE) sequence
  list_report.md    -- counts per band/tier + every exclusion by reason

Never a static list: every run re-applies every filter against the current
DB state, so a suppression or cooldown added since the last run takes effect
immediately.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

from lge.journey.build import build_journey
from lge.journey.model import Contact, Firm, JourneyLead, JourneyResult, Signal
from lge.registry import RunContext, RunResult, component

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_OUT_DIR = _PROJECT_ROOT / "data" / "out"

_BAND_RANK = {"STRIKE": 0, "SEQUENCE": 1, "NURTURE": 2}
_CONTEST_RANK = {"NONE": 0, "LOW": 1, "MED": 2, "HIGH": 3, None: 4}
_ROLE_RANK = {"owner": 0, "admin": 1, "attorney": 2, "unknown": 3, None: 4}
_EMAIL_STATUS_RANK = {"valid": 0, "catch_all": 1, "unverified": 2, "risky": 3, "invalid": 4}

_CSV_COLUMNS = [
    "firm",
    "domain",
    "city",
    "state",
    "tier",
    "wedge_sku",
    "fee_model",
    "primary_practice",
    "cms",
    "fit",
    "intent",
    "band",
    "contest",
    "signal_kind",
    "signal_evidence",
    "contact_name",
    "contact_title",
    "contact_role",
    "email",
    "email_verified",
    "vendor_email_status",
    "phone",
]

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str, firm_id: object) -> str:
    # firm_id comes back from psycopg as a uuid.UUID, not a str -- stringify
    # before slicing.
    base = _SLUG_RE.sub("-", (name or "firm").lower()).strip("-") or "firm"
    return f"{base}-{str(firm_id)[:8]}"


def _parse_now(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(UTC)
    dt = datetime.fromisoformat(raw)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Data access -- every read below is a plain, bounded, non-N+1 query keyed on
# an id list gathered from the prior step.
# ---------------------------------------------------------------------------


def _fetch_candidate_leads(conn, at: datetime) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              l.id AS lead_id, l.grade, l.band, l.contest, l.wedge_sku,
              l.fit_score, l.intent_score, l.arming_signal, l.contact_id,
              f.id AS firm_id, f.canonical_name, f.domain, f.city, f.state,
              f.tier, f.fee_model, f.primary_practice, f.cms_detected,
              COALESCE(ft.track, 'cold') AS firm_track
            FROM lead l
            JOIN firm f ON f.id = l.firm_id
            LEFT JOIN firm_track ft ON ft.firm_id = f.id
            WHERE l.closed_at IS NULL
              AND l.band IS NOT NULL
              AND l.band <> 'HOLD'
              AND (l.cooldown_until IS NULL OR l.cooldown_until < %(at)s)
              AND f.tier IS NOT NULL
              AND f.tier NOT LIKE 'DQ%%'
              AND f.tier <> 'UNCLASSIFIED'
              AND COALESCE(ft.track, 'cold') NOT IN ('portal', 'displacement')
              AND NOT EXISTS (
                SELECT 1 FROM suppression s
                WHERE s.scope = 'firm_id' AND s.value = f.id::text
              )
              AND NOT (
                f.domain IS NOT NULL AND EXISTS (
                  SELECT 1 FROM suppression s
                  WHERE s.scope = 'domain' AND s.value = f.domain
                )
              )
            ORDER BY f.canonical_name
            """,
            {"at": at},
        )
        return cur.fetchall()


def _fetch_signals(conn, signal_ids: list[int]) -> dict[int, dict]:
    if not signal_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, kind, first_seen, last_seen, closed_at, repost_count, evidence
            FROM signal WHERE id = ANY(%s)
            """,
            (signal_ids,),
        )
        return {row["id"]: row for row in cur.fetchall()}


def _fetch_repost_first_seen(conn, signal_rows: list[dict]) -> dict[int, date | None]:
    """First sighting whose board_posted_date moved past our own first_seen --
    the repost event itself, per context/20-signals/04-dedupe-dates-and-
    closure.md. Only meaningful for signals with repost_count >= 1."""
    ids = [s["id"] for s in signal_rows if (s.get("repost_count") or 0) >= 1]
    if not ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ss.signal_id, MIN(ss.board_posted_date) AS repost_date
            FROM signal_sighting ss
            JOIN signal s ON s.id = ss.signal_id
            WHERE ss.signal_id = ANY(%s)
              AND ss.board_posted_date IS NOT NULL
              AND ss.board_posted_date > s.first_seen::date
            GROUP BY ss.signal_id
            """,
            (ids,),
        )
        return {row["signal_id"]: row["repost_date"] for row in cur.fetchall()}


def _fetch_contacts(conn, firm_ids: list[str]) -> dict[str, list[dict]]:
    if not firm_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, firm_id, full_name, title, role, phone_direct "
            "FROM contact WHERE firm_id = ANY(%s)",
            (firm_ids,),
        )
        by_firm: dict[str, list[dict]] = {}
        for row in cur.fetchall():
            by_firm.setdefault(row["firm_id"], []).append(row)
        return by_firm


def _fetch_emails(conn, contact_ids: list[str]) -> dict[str, list[dict]]:
    if not contact_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT contact_id, email, status, vendor_status "
            "FROM contact_email WHERE contact_id = ANY(%s)",
            (contact_ids,),
        )
        by_contact: dict[str, list[dict]] = {}
        for row in cur.fetchall():
            by_contact.setdefault(row["contact_id"], []).append(row)
        return by_contact


# ---------------------------------------------------------------------------
# Contact selection -- "capture both people, not one": prefer owner/admin,
# include both when both exist. Ranking is independent of lead.contact_id
# (which some other component set at qualification time and may not be the
# best-emailable contact today) but is deterministic and documented.
# ---------------------------------------------------------------------------


def _best_email(emails: list[dict]) -> dict | None:
    if not emails:
        return None
    return min(emails, key=lambda e: _EMAIL_STATUS_RANK.get(e["status"], 9))


def _contact_sort_key(contact: dict, emails_by_contact: dict[str, list[dict]]) -> tuple:
    best = _best_email(emails_by_contact.get(contact["id"], []))
    email_rank = _EMAIL_STATUS_RANK.get(best["status"], 9) if best else 9
    has_phone = 0 if contact.get("phone_direct") else 1
    return (_ROLE_RANK.get(contact.get("role"), 4), email_rank, has_phone)


def _select_contacts(
    contacts: list[dict], emails_by_contact: dict[str, list[dict]]
) -> tuple[dict | None, dict | None]:
    """(primary, secondary). secondary is the other owner/admin, when one
    exists and has an email or phone to offer -- None otherwise."""
    if not contacts:
        return None, None
    usable = [
        c for c in contacts if emails_by_contact.get(c["id"]) or c.get("phone_direct")
    ]
    if not usable:
        return None, None
    ranked = sorted(usable, key=lambda c: _contact_sort_key(c, emails_by_contact))
    primary = ranked[0]
    secondary = next(
        (
            c
            for c in ranked[1:]
            if c.get("role") in ("owner", "admin") and c.get("role") != primary.get("role")
        ),
        None,
    )
    return primary, secondary


# ---------------------------------------------------------------------------
# Row assembly
# ---------------------------------------------------------------------------


def _csv_row(
    lead: dict,
    contact: dict | None,
    emails_by_contact: dict[str, list[dict]],
    signal: Signal | None,
) -> dict:
    email_row = _best_email(emails_by_contact.get(contact["id"], [])) if contact else None
    return {
        "firm": lead["canonical_name"],
        "domain": lead["domain"] or "",
        "city": lead["city"] or "",
        "state": lead["state"] or "",
        "tier": lead["tier"] or "",
        "wedge_sku": lead["wedge_sku"] or "",
        "fee_model": lead["fee_model"] or "",
        "primary_practice": lead["primary_practice"] or "",
        "cms": lead["cms_detected"] or "",
        "fit": lead["fit_score"] if lead["fit_score"] is not None else "",
        "intent": lead["intent_score"] if lead["intent_score"] is not None else "",
        "band": lead["band"],
        "contest": lead["contest"] or "",
        "signal_kind": signal.kind if signal else "",
        "signal_evidence": json.dumps(signal.evidence, ensure_ascii=False) if signal else "",
        "contact_name": contact["full_name"] if contact else "",
        "contact_title": (contact.get("title") or "") if contact else "",
        "contact_role": (contact.get("role") or "") if contact else "",
        "email": email_row["email"] if email_row else "",
        "email_verified": "true" if email_row and email_row["status"] == "valid" else "false",
        "vendor_email_status": (email_row.get("vendor_status") or "") if email_row else "",
        "phone": (contact.get("phone_direct") or "") if contact else "",
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_draft(path: Path, lead: dict, contact: dict, result: JourneyResult) -> None:
    contact_title = contact.get("title") or contact.get("role") or "unknown title"
    lines = [
        f"# {lead['canonical_name']}",
        "",
        f"Band: {lead['band']}",
        f"Contact: {contact['full_name']} ({contact_title})",
        "",
    ]
    for touch in result.touches:
        lines.append(f"## Touch {touch.step} -- Day {touch.day}")
        lines.append("")
        lines.append(f"Subject: {touch.subject}")
        lines.append("")
        lines.append(touch.body)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_report(
    path: Path,
    band_counts: Counter,
    tier_counts: Counter,
    exclusions: Counter,
    totals: dict[str, int],
) -> None:
    lines = ["# List report", ""]
    lines.append(f"Candidate leads considered: {totals['candidates']}")
    lines.append(f"Included on leads_ranked.csv: {totals['ranked']}")
    lines.append(f"Included on phone_list.csv: {totals['phone']}")
    lines.append("")
    lines.append("## By band (leads_ranked.csv)")
    for band in ("STRIKE", "SEQUENCE", "NURTURE"):
        lines.append(f"- {band}: {band_counts.get(band, 0)}")
    lines.append("")
    lines.append("## By tier (leads_ranked.csv)")
    for tier, count in sorted(tier_counts.items()):
        lines.append(f"- {tier}: {count}")
    lines.append("")
    lines.append("## Exclusions by reason")
    if not exclusions:
        lines.append("- none")
    for reason, count in sorted(exclusions.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- {reason}: {count}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# The component
# ---------------------------------------------------------------------------


@component(
    "build_list",
    "export",
    "Builds leads_ranked.csv, strike.csv, phone_list.csv, drafts/ and "
    "list_report.md under data/out/ -- list hygiene applied at build time.",
)
def build_list(ctx: RunContext, **opts: object) -> RunResult:
    out_dir = Path(str(opts["out_dir"])) if opts.get("out_dir") else _DEFAULT_OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    drafts_dir = out_dir / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)

    at = _parse_now(str(opts["now"]) if opts.get("now") else None)

    leads = _fetch_candidate_leads(ctx.conn, at)
    firm_ids = [row["firm_id"] for row in leads]
    signal_ids = [row["arming_signal"] for row in leads if row["arming_signal"] is not None]

    signals_by_id = _fetch_signals(ctx.conn, signal_ids)
    repost_by_signal_id = _fetch_repost_first_seen(ctx.conn, list(signals_by_id.values()))
    contacts_by_firm = _fetch_contacts(ctx.conn, firm_ids)
    all_contact_ids = [c["id"] for contacts in contacts_by_firm.values() for c in contacts]
    emails_by_contact = _fetch_emails(ctx.conn, all_contact_ids)

    ranked_rows: list[dict] = []
    strike_rows: list[dict] = []
    phone_rows: list[dict] = []
    band_counts: Counter = Counter()
    tier_counts: Counter = Counter()
    exclusions: Counter = Counter()
    drafts_written = 0

    for lead in leads:
        signal_row = signals_by_id.get(lead["arming_signal"])
        signal = (
            Signal(
                id=signal_row["id"],
                kind=signal_row["kind"],
                first_seen=signal_row["first_seen"],
                last_seen=signal_row["last_seen"],
                closed_at=signal_row["closed_at"],
                repost_count=signal_row["repost_count"] or 0,
                evidence=signal_row["evidence"] or {},
            )
            if signal_row
            else None
        )

        contacts = contacts_by_firm.get(lead["firm_id"], [])
        primary, secondary = _select_contacts(contacts, emails_by_contact)

        if lead["grade"] == "B":
            if primary is not None:
                phone_rows.append(_csv_row(lead, primary, emails_by_contact, signal))
            continue

        if lead["grade"] != "A":
            exclusions["grade_not_set"] += 1
            continue

        if primary is None:
            exclusions["no_usable_contact"] += 1
            continue

        if lead["band"] == "STRIKE":
            row = _csv_row(lead, primary, emails_by_contact, signal)
            ranked_rows.append(row)
            strike_rows.append(row)
            if secondary is not None:
                second_row = _csv_row(lead, secondary, emails_by_contact, signal)
                ranked_rows.append(second_row)
                strike_rows.append(second_row)
            band_counts["STRIKE"] += 1
            tier_counts[lead["tier"]] += 1
            continue

        # SEQUENCE / NURTURE: render the journey. A lead that fails to
        # render (unresolved token, missing signal evidence, unresolved fee
        # model, ...) never reaches leads_ranked.csv or drafts/ -- "a token
        # that cannot resolve means the lead does not go out."
        firm = Firm(
            id=str(lead["firm_id"]),
            canonical_name=lead["canonical_name"],
            city=lead["city"],
            state=lead["state"],
            tier=lead["tier"],
            fee_model=lead["fee_model"],
            primary_practice=lead["primary_practice"],
            cms_detected=lead["cms_detected"],
        )
        contact = Contact(
            id=str(primary["id"]),
            full_name=primary["full_name"],
            title=primary.get("title"),
            role=primary.get("role"),
        )
        journey_lead = JourneyLead(
            lead_id=str(lead["lead_id"]),
            band=lead["band"],
            firm=firm,
            contact=contact,
            signal=signal,
            repost_first_seen=repost_by_signal_id.get(signal.id) if signal else None,
            at=at,
        )
        result = build_journey(journey_lead)
        if result.excluded_reason is not None:
            exclusions[result.excluded_reason] += 1
            continue

        ranked_rows.append(_csv_row(lead, primary, emails_by_contact, signal))
        if secondary is not None:
            # "Capture both people, not one": the secondary owner/admin
            # contact is informational on the list (a human sender should
            # know both names) but the rendered draft still addresses only
            # the primary contact -- a 9-touch sequence has one recipient.
            ranked_rows.append(_csv_row(lead, secondary, emails_by_contact, signal))
        band_counts[lead["band"]] += 1
        tier_counts[lead["tier"]] += 1

        slug = _slugify(lead["canonical_name"], lead["firm_id"])
        _write_draft(drafts_dir / f"{slug}.md", lead, primary, result)
        drafts_written += 1

    ranked_rows.sort(
        key=lambda r: (
            _BAND_RANK.get(r["band"], 9),
            -(r["intent"] if isinstance(r["intent"], int) else -1),
            _CONTEST_RANK.get(r["contest"] or None, 4),
        )
    )
    strike_rows.sort(key=lambda r: -(r["intent"] if isinstance(r["intent"], int) else -1))

    _write_csv(out_dir / "leads_ranked.csv", ranked_rows)
    _write_csv(out_dir / "strike.csv", strike_rows)
    _write_csv(out_dir / "phone_list.csv", phone_rows)
    _write_report(
        out_dir / "list_report.md",
        band_counts,
        tier_counts,
        exclusions,
        {"candidates": len(leads), "ranked": len(ranked_rows), "phone": len(phone_rows)},
    )

    return RunResult(
        processed=len(ranked_rows),
        skipped=sum(exclusions.values()),
        failed=0,
        notes=[
            f"leads_ranked={len(ranked_rows)} strike={len(strike_rows)} "
            f"phone={len(phone_rows)} drafts={drafts_written}",
        ],
    )
