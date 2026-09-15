"""The stage a lead is at, as a person works it, and what to do next.

The engine's sixteen states (context/40-pipeline/05-lead-lifecycle.md) say
what the machine has done. An SDR needs fewer, task-shaped answers: is it
being researched, does it need a decision, does it need a person, is it
ready to reach, is it parked, is someone talking to it, is it closed. The
stage is derived -- never stored -- from the state, the cooldown, and
whether a contact with an address is on the lead (D-036).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

STAGE_DISPLAY: dict[str, str] = {
    "researching": "Researching",
    "no_website": "No website",
    "needs_review": "Needs a decision",
    "needs_contact": "Needs a person",
    "ready": "Ready to reach",
    "parked": "Parked",
    "in_outreach": "In outreach",
    "replied": "Replied",
    "handed_off": "Handed off",
    "won": "Won",
    "lost": "Lost",
    "disqualified": "Disqualified",
    "do_not_contact": "Do not contact",
    "needs_refresh": "Needs a refresh",
}

_RESEARCHING = {"DISCOVERED", "PROFILING", "PROFILED", "ESCALATED"}
_QUALIFIED = {"QUALIFIED_A", "QUALIFIED_B"}

# The work queue's order: what needs a person first, then what is waiting.
STAGE_ORDER: tuple[str, ...] = (
    "needs_review", "needs_contact", "ready", "in_outreach", "replied", "parked",
    "researching", "no_website", "needs_refresh", "handed_off", "won", "lost",
    "disqualified", "do_not_contact",
)

# What each stage means, for the landing page's glossary and the queue's tabs.
STAGE_HELP: dict[str, str] = {
    "researching": "The engine is reading the site, or has not reached it yet.",
    "no_website": "No site could be read; the firm needs a website on record.",
    "needs_review": "Researched and tiered; a person decides whether to pursue it.",
    "needs_contact": "Worth pursuing, but no decision-maker with an address yet.",
    "ready": "A named person with an address; write when a signal arms it, or now.",
    "parked": "Held until a date you chose.",
    "in_outreach": "The sequence is running.",
    "replied": "They answered; a person takes it from here.",
    "handed_off": "With sales.",
    "won": "Closed won.",
    "lost": "Closed lost; returns to the pool after the cooldown.",
    "disqualified": "Not a fit, by the tier or by a person's decision.",
    "do_not_contact": "Opted out or bounced; never emailed again.",
    "needs_refresh": "The site changed or the record is old; research again.",
}


def stage_sql(lead: str = "l") -> str:
    """The same rule as `stage_of`, as a SQL expression over the open lead
    `lead` -- so the work queue can page and count by stage in the database.
    The contact is the firm's owner or office manager (the primary the row
    shows), the address any email on file for them."""
    has_contact = (
        f"EXISTS (SELECT 1 FROM contact sc WHERE sc.firm_id = {lead}.firm_id "
        "AND sc.removed_at IS NULL AND sc.role IN ('owner', 'admin'))"
    )
    has_email = (
        f"EXISTS (SELECT 1 FROM contact sc JOIN contact_email se ON se.contact_id = sc.id "
        f"WHERE sc.firm_id = {lead}.firm_id AND sc.removed_at IS NULL "
        "AND sc.role IN ('owner', 'admin'))"
    )
    return f"""
    CASE
      WHEN {lead}.state = 'SUPPRESSED' THEN 'do_not_contact'
      WHEN {lead}.state = 'WON' THEN 'won'
      WHEN {lead}.state = 'LOST' THEN 'lost'
      WHEN {lead}.state = 'HANDOFF' THEN 'handed_off'
      WHEN {lead}.state = 'RESPONDED' THEN 'replied'
      WHEN {lead}.state = 'ENGAGED' THEN 'in_outreach'
      WHEN {lead}.state = 'DISQUALIFIED' THEN 'disqualified'
      WHEN {lead}.state = 'STALE' THEN 'needs_refresh'
      WHEN {lead}.state = 'NO_WEB' THEN 'no_website'
      WHEN {lead}.state IN ('DISCOVERED', 'PROFILING', 'PROFILED', 'ESCALATED') THEN 'researching'
      WHEN {lead}.cooldown_until IS NOT NULL AND {lead}.cooldown_until > now() THEN 'parked'
      WHEN {lead}.state = 'ARMED' THEN 'ready'
      WHEN {lead}.state IN ('QUALIFIED_A', 'QUALIFIED_B') THEN
        CASE WHEN {has_contact} AND {has_email} THEN 'ready' ELSE 'needs_contact' END
      WHEN {lead}.state = 'RESOLVED' THEN
        CASE WHEN {has_email} THEN 'needs_review' ELSE 'needs_contact' END
      WHEN {lead}.state = 'CONTACT_PENDING' THEN 'needs_contact'
      WHEN {lead}.state = 'CLASSIFIED' THEN 'needs_review'
      ELSE 'researching'
    END
    """


def stage_of(
    state: str | None,
    *,
    cooldown_until: Any = None,
    contact_name: str | None = None,
    has_email: bool = False,
    now: datetime | None = None,
) -> tuple[str, str]:
    """(stage, next action) for a lead."""
    now = now or datetime.now(UTC)
    state = state or "DISCOVERED"
    parked = cooldown_until is not None and _as_datetime(cooldown_until) > now

    if state == "SUPPRESSED":
        return "do_not_contact", "Nothing -- the firm opted out or bounced"
    if state == "WON":
        return "won", "Nothing -- sales closed it"
    if state == "LOST":
        return "lost", "Wait for the cooldown; it returns to the pool"
    if state == "HANDOFF":
        return "handed_off", "Sales owns it -- record won or lost"
    if state == "RESPONDED":
        return "replied", "Read the reply; hand off, park, or opt out"
    if state == "ENGAGED":
        return "in_outreach", "Wait for the next touch or a reply"
    if state == "DISQUALIFIED":
        return "disqualified", "Reopen if the reason was wrong"
    if state == "STALE":
        return "needs_refresh", "Research the site again"
    if state == "NO_WEB":
        return "no_website", "Find the firm's website, then research"
    if state in _RESEARCHING:
        return "researching", (
            "Research the site" if state == "DISCOVERED" else "Wait for research to finish"
        )
    if parked:
        until = _as_datetime(cooldown_until).date().isoformat()
        return "parked", f"Parked until {until}"
    if state == "ARMED":
        return "ready", "Send touch 1"
    if state in _QUALIFIED:
        if contact_name and has_email:
            return "ready", "Send touch 1 when a signal arms it, or hand off now"
        if contact_name:
            return "needs_contact", f"Find an email for {contact_name}"
        return "needs_contact", "Find a decision-maker"
    if state == "RESOLVED":
        if has_email:
            return "needs_review", "Qualify or disqualify"
        return "needs_contact", f"Find an email for {contact_name or 'the contact'}"
    if state == "CONTACT_PENDING":
        return "needs_contact", "Find a decision-maker (owner or administrator)"
    if state == "CLASSIFIED":
        return "needs_review", "Review the record; qualify or disqualify"
    return "researching", "Wait for research to finish"


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime(value.year, value.month, value.day, tzinfo=UTC)
