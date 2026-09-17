"""Every plain-word string the API returns. plan/api-contract.md: "Display
strings come from the backend ... the frontend never humanises a slug,
recomputes a tier, filters a list or renders a draft." This module is where
that rule lives for everything that is not already humanised upstream
(`lge.journey.tokens` owns {role}/{practice}/{cms} token humanisation for
outreach copy -- reused here via import, never re-implemented) or generated
by the engine itself (`build_journey`, `build_list`, `resolve_claims`).

Pure functions only -- no DB access, so every mapping is unit-testable
without Postgres.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from lge.journey.tokens import (
    days_open as _days_open,
)
from lge.journey.tokens import (
    humanize_cms,
    humanize_practice,
    role_from_evidence,
    tort_from_evidence,
)

UNKNOWN_DISPLAY = "Unknown — not guessed"

# =============================================================================
# Source labels -- plan/api-contract.md "Source labels" table, verbatim.
# Prefix-matched tags (llm:p8:*, llm:p9:*) and a defensive fallback for
# sources config/precedence.yml documents as "not yet emitting claims" today
# (places, bar:<state>, directory:<name>, ats:<slug>) so this file does not
# need editing the day one of them starts writing -- same intent as that
# config file's own comment.
# =============================================================================

_SOURCE_LABELS: dict[str, str] = {
    "site:jsonld": "Firm website (structured data)",
    "regex:p6": "Firm website (fee language)",
    "rules:p7": "Firm website (page code)",
    "rules:practice": "Firm website (practice pages)",
    "rules:site": "Firm website",
    "site:page": "Firm website (page text)",
    "search:ddg": "Web search (DuckDuckGo)",
    "search:serper": "Web search (Google)",
    "search:brave": "Web search (Brave)",
    "hunter": "Hunter.io",
    "internal_firms": "Purchased firm list",
    "internal_jobs": "Job history file",
    "careers": "Careers page",
}

_SOURCE_PREFIX_LABELS: tuple[tuple[str, str], ...] = (
    ("llm:p9:", "Firm website (read by AI, escalated)"),
    ("llm:p8:", "Firm website (read by AI)"),
    ("bar_board:", "Job board"),
    ("ats:", "Employer's applicant tracking system"),
    ("licensed:", "Licensed job-board aggregator"),
    ("bar:", "State bar record"),
    ("directory:", "Legal directory"),
)

_SOURCE_FALLBACK: dict[str, str] = {
    "places": "Google Places",
    "serp": "Search results",
}


def source_label(tag: str | None) -> str:
    """A source tag -> the plain-English string a human reads on a claim or
    a piece of proof. Never raises -- an unrecognised tag still gets a
    readable (if generic) label rather than leaking an internal slug."""
    if not tag:
        return "Unknown source"
    if tag in _SOURCE_LABELS:
        return _SOURCE_LABELS[tag]
    for prefix, label in _SOURCE_PREFIX_LABELS:
        if tag.startswith(prefix):
            return label
    if tag in _SOURCE_FALLBACK:
        return _SOURCE_FALLBACK[tag]
    return tag.replace(":", " ").replace("_", " ").strip().capitalize()


# =============================================================================
# Lead lifecycle state -- context/40-pipeline/05-lead-lifecycle.md's 16 states.
# =============================================================================

_STATE_DISPLAY: dict[str, str] = {
    "DISCOVERED": "Discovered — not crawled yet",
    "PROFILING": "Being profiled",
    "NO_WEB": "No website we can read",
    "PROFILED": "Profiled — awaiting classification",
    "CLASSIFIED": "Classified",
    "ESCALATED": "Escalated for a closer look",
    "DISQUALIFIED": "Disqualified",
    "CONTACT_PENDING": "Finding a contact",
    "RESOLVED": "Resolved — waiting on email verification",
    "QUALIFIED_A": "Qualified — email verified",
    "QUALIFIED_B": "Qualified — phone only, email not verifiable",
    "ARMED": "Armed — ready to contact",
    "ENGAGED": "Engaged — sequence running",
    "RESPONDED": "Responded",
    "HANDOFF": "Handed off to sales",
    "WON": "Won",
    "LOST": "Lost",
    "STALE": "Stale — needs a refresh",
    "SUPPRESSED": "Suppressed",
}


def state_display(state: str | None) -> str:
    if not state:
        return "Unknown state"
    return _STATE_DISPLAY.get(state, state.replace("_", " ").capitalize())


# =============================================================================
# List-hygiene reasons -- lge/export/list.py's codes (structural exclusions,
# grade/contact checks, journey render failures) in plain words. Shown as a
# lead's `blockers` on the band tabs and as `exclusion_reasons` in the detail.
# =============================================================================

_REASON_DISPLAY: dict[str, str] = {
    "tier_unclassified": "Fee model unknown — not tiered yet",
    "tier_not_set": "Not tiered yet",
    "grade_not_set": "Email not verified",
    "no_usable_contact": "No owner or office manager found",
    "band_hold": "Score too low",
    "cooldown": "On cooldown",
    "tier_disqualified": "Disqualified",
    "suppressed_firm": "Suppressed",
    "suppressed_domain": "Suppressed",
    "firm_track_portal": "Existing portal customer",
    "firm_track_displacement": "Displacement track",
}


def reason_display(code: str | None) -> str:
    if not code:
        return "Unknown reason"
    if code in _REASON_DISPLAY:
        return _REASON_DISPLAY[code]
    if code.startswith("missing_"):
        what = code.removeprefix("missing_").replace("_", " ")
        return f"Draft cannot be written — missing {what}"
    return code.replace("_", " ").strip().capitalize()


# =============================================================================
# Email status -- contact_email.status -> plan/api-contract.md's exact copy.
# =============================================================================


def email_status_display(status: str | None, vendor_status: str | None) -> str | None:
    if not status:
        return None
    if status == "valid":
        return "Verified"
    if status == "unverified":
        return f"Unverified — vendor says {vendor_status}" if vendor_status else "Unverified"
    if status == "catch_all":
        return "Catch-all — failure"
    if status == "risky":
        return "Risky — failure"
    if status == "invalid":
        return "Invalid"
    return status.replace("_", " ").capitalize()


# =============================================================================
# Tier -- sql/002_functions.sql's icp_tier(), context/10-icp/
# 05-tiers-and-wedge-skus.md.
# =============================================================================

_TIER_DISPLAY: dict[str, str] = {
    "1A": "Tier 1A",
    "1B": "Tier 1B",
    "2": "Tier 2",
    "3": "Tier 3",
    "4_NONBILLABLE": "Tier 4",
    "UNCLASSIFIED": "Unclassified",
}

_ENTITY_KIND_LABEL: dict[str, str] = {
    "gov": "a government office",
    "inhouse": "an in-house legal department",
    "directory_stub": "a directory listing, not a firm",
}

_DQ_DISPLAY: dict[str, str] = {
    "DQ_ENTITY": "Disqualified — not a private firm",
    "DQ_GEO": "Disqualified — outside the US",
    "DQ_SIZE": "Disqualified — over 50 attorneys",
    "DQ_SELFSERVE": "Disqualified — has in-house recruiting",
    "DQ_NOVOLUME": "Disqualified — practice has no delegable volume",
    "DQ_NOBUDGET": "Disqualified — new solo practice, no ad spend",
}

_FEE_DISPLAY: dict[str, str] = {
    "contingency": "Contingency",
    "fee_shifting": "Fee-shifting",
    "flat": "Flat fee",
    "hourly": "Hourly",
    "mixed": "Mixed fee",
}

_PRACTICE_TIER_NAME: dict[str, str] = {
    "personal_injury": "personal-injury",
    "mass_tort": "mass-tort",
    "immigration": "immigration",
    "employment": "employment",
    "lemon_law": "lemon-law",
    "workers_comp": "workers'-comp",
    "ssdi": "SSDI",
    "consumer": "consumer-law",
    "bankruptcy": "bankruptcy",
    "criminal": "criminal-defense",
    "estate": "estate-planning",
    "family": "family-law",
}


def tier_display(tier: str | None) -> str:
    if not tier:
        return "Not yet classified"
    if tier in _DQ_DISPLAY:
        return _DQ_DISPLAY[tier]
    return _TIER_DISPLAY.get(tier, tier)


def fee_display(fee_model: str | None) -> str | None:
    if fee_model is None:
        return None
    if fee_model == "unknown":
        return UNKNOWN_DISPLAY
    return _FEE_DISPLAY.get(fee_model, fee_model.replace("_", " ").capitalize())


def practice_display(primary_practice: str | None) -> str | None:
    if primary_practice is None:
        return None
    if primary_practice == "unknown":
        return UNKNOWN_DISPLAY
    return humanize_practice(primary_practice)


def cms_display(cms_detected: str | None) -> str | None:
    return humanize_cms(cms_detected)


def tier_reason(firm: dict[str, Any]) -> str:
    """A one-sentence explanation of `firm['tier']`, derived from the same
    columns and the same evaluation order as `icp_tier()`
    (sql/002_functions.sql) -- hard disqualifiers first, then fee_model
    before practice_area. This EXPLAINS an already-computed tier; it never
    recomputes one (that would be exactly the re-implementation
    plan/api-contract.md forbids)."""
    tier = firm.get("tier")
    entity_kind = firm.get("entity_kind")
    country = firm.get("country")
    attorney_count = firm.get("attorney_count")
    primary_practice = firm.get("primary_practice")
    fee_model = firm.get("fee_model")
    paid_ads_active = firm.get("paid_ads_active")

    if tier is None:
        return "Not yet crawled, so not classified."

    if tier == "DQ_ENTITY":
        kind_label = _ENTITY_KIND_LABEL.get(entity_kind, "not a private firm")
        return f"{kind_label[0].upper()}{kind_label[1:]}, so disqualified."
    if tier == "DQ_GEO":
        where = f" ({country})" if country else ""
        return f"Located outside the US{where}, so disqualified."
    if tier == "DQ_SIZE":
        return f"{attorney_count} attorneys, over the 50-attorney limit, so disqualified."
    if tier == "DQ_SELFSERVE":
        return "Has an in-house recruiter, so self-serve and disqualified."
    if tier == "DQ_NOVOLUME":
        practice_label = practice_display(primary_practice) or "This practice area"
        return f"{practice_label} has no delegable procedural volume, so disqualified."
    if tier == "DQ_NOBUDGET":
        return (
            "A new solo practice with no paid advertising yet, so disqualified."
            if not paid_ads_active
            else "A new solo practice, so disqualified."
        )

    fee_label = fee_display(fee_model) or "an unknown fee model"
    practice_label = practice_display(primary_practice) or "an unknown practice area"

    if tier == "1A":
        return f"{fee_label} and a {practice_label} practice, so tier 1A."
    if tier == "1B":
        return "Flat fee and an immigration practice, so tier 1B."
    if tier == "2":
        return f"{fee_label} and a {practice_label} practice, so tier 2."
    if tier == "3":
        return f"Flat fee and a {practice_label} practice, so tier 3."
    if tier == "4_NONBILLABLE":
        return "Hourly billing, so tier 4 — only non-billable roles are sellable here."

    if tier == "UNCLASSIFIED":
        if fee_model in (None, "unknown"):
            return "Fee model unknown — not guessed — so unclassified."
        if primary_practice in (None, "unknown"):
            return "Practice area unknown — not guessed — so unclassified."
        return "Fee model and practice area don't match a defined tier, so unclassified."

    return f"Tier {tier}."


# =============================================================================
# Attribute display -- GET /api/firms/{id}'s AttributeRow.
# =============================================================================

_ATTR_LABELS: dict[str, str] = {
    "entity_kind": "Entity kind",
    "attorney_count": "Attorney count",
    "staff_ratio": "Staff ratio",
    "primary_practice": "Primary practice",
    "practice_areas": "Practice areas",
    "fee_model": "Fee model",
    "spanish_intake": "Spanish intake",
    "cms_detected": "Case management system",
    "review_count": "Review count",
    "paid_ads_active": "Paid ads active",
    "has_inhouse_recruiter": "In-house recruiter",
    "country": "Country",
    "first_seen_bar_admission": "First bar admission seen",
    "has_hired_support_roles": "Has hired support roles before",
    "support_roles_posted": "Support roles posted",
    "last_known_hiring_attempt": "Last known hiring attempt",
    "repeat_role_count": "Repeat role count",
    "canonical_name": "Firm name",
    "phone_e164": "Phone",
    "address": "Address",
    "city": "City",
    # Informational-only claims (never reconciled onto a firm column) --
    # shown for provenance, per the build brief: "clear labels ('Vendor
    # practice hint (not used for tier)')".
    "vendor_practice_hint": "Vendor practice hint (not used for tier)",
    "vendor_size_contradiction": "Vendor size contradiction (not used for tier)",
    "vendor_headcount_range": "Vendor headcount range (not used for tier)",
    "email_pattern": "Email pattern",
    "languages": "Languages (not used for tier)",
    "site_emails": "Emails on the site (not used for tier)",
    "general_email": "General inbox",
    "hiring_email": "Hiring inbox",
    # px_site_facts (D-031): what the firm's own pages say.
    "office_locations": "Offices on the site",
    "office_count": "Office count",
    "site_people": "People named on the site",
    "staff_listed": "Staff listed on the site",
    "testimonials": "Client testimonials on the site",
    "site_review_summary": "Reviews the site advertises",
    "social_links": "Social profiles",
    "review_profiles": "Review profiles",
    "google_maps_url": "Google Maps listing",
    "recent_posts": "Recent posts",
    "latest_post_date": "Latest post",
    "growth_news": "Growth news",
    "live_chat_vendor": "Live chat vendor",
    "online_intake_form": "Online intake form",
    "copyright_year": "Copyright year in the footer",
    "site_gaps": "What the site lacks",
    # r_search_links (D-032): what a web search says.
    "google_business_url": "Google Business listing",
    "google_rating": "Google rating",
    "search_review_snippets": "Review snippets from search (not used for tier)",
    "search_emails": "Addresses found by search (not used for tier)",
    "linkedin_company_url": "LinkedIn company page",
    "linkedin_headcount": "Headcount on LinkedIn",
}

_GAP_LABELS: dict[str, str] = {
    "no_careers_page": "No careers page",
    "no_online_intake": "No online intake form",
    "no_live_chat": "No live chat",
    "no_spanish": "No Spanish-language page",
    "stale_copyright": "Copyright year is stale",
    "no_testimonials": "No client testimonials",
    "no_news": "No blog or news page",
    "stale_news": "Blog not updated in a year",
    "no_support_staff_listed": "No support staff listed",
    "no_social_presence": "No social profiles linked",
    "no_review_link": "No link to reviews",
}


def gap_label(gap: str) -> str:
    return _GAP_LABELS.get(gap, gap.replace("_", " ").capitalize())


def _more(shown: int, total: int) -> str:
    return f" (+{total - shown} more)" if total > shown else ""


_EMPTY_LIST_DISPLAY: dict[str, str] = {
    "site_people": "Nobody named on the pages read",
    "testimonials": "None on the pages read",
    "recent_posts": "No dated posts on the pages read",
    "growth_news": "None in the last year",
    "office_locations": "No street address on the pages read",
}


def _format_site_fact(attr: str, value: Any) -> str | None:
    """The list- and dict-shaped site facts, read as a person would say them."""
    if attr in _EMPTY_LIST_DISPLAY and isinstance(value, list) and not value:
        return _EMPTY_LIST_DISPLAY[attr]  # read and found empty: not "unknown"
    if attr == "site_people" and isinstance(value, list):
        parts = [
            f"{p.get('name')} ({p['title']})" if p.get("title") else str(p.get("name"))
            for p in value[:8] if isinstance(p, dict)
        ]
        return "; ".join(parts) + _more(len(parts), len(value)) if parts else None
    if attr == "staff_listed" and isinstance(value, dict):
        return (
            f"{value.get('attorneys', 0)} attorneys, {value.get('support', 0)} support, "
            f"{value.get('other', 0)} other"
        )
    if attr == "testimonials" and isinstance(value, list):
        if not value:
            return None
        first = value[0] if isinstance(value[0], dict) else {}
        quote = str(first.get("quote") or "")[:120]
        who = f" — {first['author']}" if first.get("author") else ""
        return f"{len(value)} quote(s); “{quote}”{who}"
    if attr == "site_review_summary" and isinstance(value, dict):
        bits = []
        if value.get("rating") is not None:
            bits.append(f"{value['rating']} stars")
        if value.get("count") is not None:
            bits.append(f"{value['count']} reviews")
        return ", ".join(bits) or None
    if attr in ("social_links", "review_profiles") and isinstance(value, dict):
        return ", ".join(sorted(value)) or None
    if attr in ("recent_posts", "growth_news") and isinstance(value, list):
        parts = [
            f"{p.get('date')}: {p.get('title')}" for p in value[:3] if isinstance(p, dict)
        ]
        return "; ".join(parts) + _more(len(parts), len(value)) if parts else None
    if attr == "office_locations" and isinstance(value, list):
        parts = [
            f"{o.get('city')}, {o.get('state')}" for o in value[:6] if isinstance(o, dict)
        ]
        return "; ".join(parts) + _more(len(parts), len(value)) if parts else None
    if attr == "site_gaps" and isinstance(value, list):
        if not value:
            return "Nothing missing among the pages read"
        return ", ".join(gap_label(g["gap"]) for g in value if isinstance(g, dict))
    if attr in ("google_maps_url", "google_business_url") and isinstance(value, str):
        # A Maps/search URL runs to hundreds of characters; the host and the
        # start of the query say what it is.
        return value.split("://", 1)[-1][:72] + ("…" if len(value) > 75 else "")
    if attr == "search_review_snippets" and isinstance(value, list):
        parts = [str(s.get("body") or s.get("title") or "")[:100] for s in value[:2]
                 if isinstance(s, dict)]
        return "; ".join(p for p in parts if p) + _more(len(parts), len(value)) or None
    return None


def attr_label(attr: str) -> str:
    return _ATTR_LABELS.get(attr, attr.replace("_", " ").capitalize())


def format_attr_value(attr: str, value: Any) -> str | None:
    """A claim or resolved value -> a display string. `None` and the
    literal 'unknown' both render as the same explicit, never-blank
    string -- ui-plan.md: "unknown is first-class ... never a blank"."""
    if value is None or value == "unknown":
        return UNKNOWN_DISPLAY
    if attr == "fee_model":
        return fee_display(value)
    if attr == "primary_practice":
        return practice_display(value)
    if attr == "cms_detected":
        return cms_display(value)
    site_fact = _format_site_fact(attr, value)
    if site_fact is not None:
        return site_fact
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple)):
        items = [str(v) for v in value if v is not None]
        return ", ".join(items) if items else UNKNOWN_DISPLAY
    if isinstance(value, dict):
        parts = [f"{k}: {v}" for k, v in value.items() if v is not None]
        return "; ".join(parts) if parts else UNKNOWN_DISPLAY
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


# =============================================================================
# Proof headline -- the arming signal rendered plainly. Reuses
# lge.journey.tokens' evidence readers (role_from_evidence, tort_from_evidence,
# days_open, humanize_cms) rather than re-parsing evidence shapes here.
# =============================================================================

_SMALL_NUMBER_WORDS = {2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six"}

_GENERIC_KIND_HEADLINE: dict[str, str] = {
    "paid_ads_spike": "Paid ad spend spiked",
    "new_office_or_lateral": "New office or lateral hire",
    "partner_intro": "Warm partner introduction",
    "pricing_page_visit": "Visited the pricing page",
    "review_unreturned_call": "Reviews mention unreturned calls",
    # ja7_pain_signals (D-033)
    "no_intake_channel": "No way to capture a lead after hours (no intake form, no chat)",
    "no_support_staff_listed": "Attorneys listed, no support staff",
    "stale_site": "Website not maintained",
}


def proof_headline(
    kind: str, evidence: dict[str, Any] | None, first_seen: Any, at: Any, repost_count: int
) -> str:
    evidence = evidence or {}
    if kind == "job_posting_open":
        role = role_from_evidence(evidence) or "Role"
        role = role[0].upper() + role[1:] if role else "Role"
        if repost_count and repost_count >= 1:
            return f"{role} role reposted"
        days = _days_open(first_seen, at)
        return f"{role} role open {days} days" if days is not None else f"{role} role open"

    if kind == "multi_opening":
        roles = evidence.get("roles")
        n = len(roles) if isinstance(roles, list) else 2
        count_word = _SMALL_NUMBER_WORDS.get(n, str(n))
        return f"{count_word} support roles open"

    if kind == "mass_tort_campaign":
        tort = tort_from_evidence(evidence) or "campaign"
        return f"Mass tort campaign: {tort}"

    if kind == "cms_implemented":
        cms = humanize_cms(evidence.get("cms")) or "a new system"
        return f"New case system: {cms}"

    return _GENERIC_KIND_HEADLINE.get(kind, kind.replace("_", " ").capitalize())
