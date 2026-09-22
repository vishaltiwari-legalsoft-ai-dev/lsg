"""build_journey -- turns one qualified lead into its rendered touch
sequence (or an exclusion reason). Pure function of a `JourneyLead`; no DB
access. `lge/export/list.py` is the only caller: it fetches rows, shapes a
`JourneyLead`, calls this, and writes whatever comes back.

Evidence-shape assumption (undocumented upstream, since no other agent's
component writes `multi_opening` rows yet): a `multi_opening` signal's
`evidence` carries `{"roles": [{...job-signal evidence...}, {...}]}}`, two
job-signal-shaped dicts. Every other kind uses the flat job-signal shape
`{title, canonical_role, posted_date, url, sources, quote}` (or, for
`mass_tort_campaign`, a `tort` key) given in the task contract. If the real
signal-acquisition component lands on a different shape for
`multi_opening`, only `_build_tokens`'s evidence handling needs to change --
nothing else in this module knows about evidence layout.
"""

from __future__ import annotations

from lge.journey.model import NO_EDITS, JourneyEdits, JourneyLead, JourneyResult, RenderedTouch
from lge.journey.render import load_template, signature, substitute
from lge.journey.select import load_config, select_touch1_variant, select_touch3_variant
from lge.journey.tokens import (
    days_open,
    format_month_name,
    format_posted_date,
    humanize_cms,
    humanize_practice,
    resolve_first_name,
    role_from_evidence,
    tort_from_evidence,
)

_CMS_FALLBACK = {"cms": "your systems"}

_STATIC_TOUCHES: dict[int, str] = {
    4: "touch4.md",
    5: "touch5.md",
    6: "touch6.md",
    7: "touch7.md",
    9: "touch9.md",
}


def _template(rel_path: str, edits: JourneyEdits) -> tuple[str | None, str]:
    """A copy file's (subject, body): the Email journey screen's wording when
    it has been changed there (D-057), else the file's own."""
    edited = edits.copy.get(rel_path)
    return edited if edited is not None else load_template(rel_path)


def _day(step: int, edits: JourneyEdits) -> int:
    """Days after email 1: the screen's edit, else journey/sequences.yml.
    The days used to be written here a second time, so a change to the
    config file -- which says a day offset "never needs a code change" --
    changed nothing."""
    if step in edits.days:
        return edits.days[step]
    return next(int(t["day"]) for t in load_config()["touches"] if int(t["step"]) == step)

_TOUCH1_FILES = {
    "1B": "touch1/1b.md",
    "1C": "touch1/1c.md",
    "1D": "touch1/1d.md",
    "1E": "touch1/1e.md",
    "1F": "touch1/1f.md",
}

_MIDDLE_FILE_FOR_TIER = {
    "1B": "touch1/_middle_1b.md",
    "2": "touch1/_middle_2.md",
    "3": "touch1/_middle_3.md",
}


def _build_tokens(lead: JourneyLead) -> dict[str, str | None]:
    signal = lead.signal
    evidence = signal.evidence if signal else None

    firm_name = (lead.firm.canonical_name or "").strip() or None

    tokens: dict[str, str | None] = {
        "first_name": resolve_first_name(lead.contact.full_name),
        "firm_name": firm_name,
        "practice": humanize_practice(lead.firm.primary_practice),
        "cms": humanize_cms(lead.firm.cms_detected),
        "city": lead.firm.city,
        "role": None,
        "role_2": None,
        "posted_date": None,
        "tort": None,
        "repost_month": None,
        "days_open": None,
    }

    # {role}/{role_2}/{tort} are only extracted for the signal kinds whose
    # evidence is actually shaped to carry them. A cms_implemented or
    # review_unreturned_call signal's evidence is NOT job-signal-shaped --
    # an incidental "title" key on it (e.g. a free-text note) must never be
    # mistaken for a job-posting role. See the module docstring's
    # evidence-shape assumption.
    if evidence and signal is not None:
        if signal.kind == "job_posting_open":
            tokens["role"] = role_from_evidence(evidence)
        elif signal.kind == "multi_opening":
            roles = evidence.get("roles")
            if isinstance(roles, list) and roles:
                tokens["role"] = role_from_evidence(roles[0])
                if len(roles) > 1:
                    tokens["role_2"] = role_from_evidence(roles[1])
        elif signal.kind == "mass_tort_campaign":
            tokens["tort"] = tort_from_evidence(evidence)

    if signal is not None:
        tokens["posted_date"] = format_posted_date(signal.first_seen)
        tokens["days_open"] = days_open(signal.first_seen, lead.at)

    if lead.repost_first_seen is not None:
        tokens["repost_month"] = format_month_name(lead.repost_first_seen)

    return tokens


def _finish(
    step: int,
    files: tuple[str, ...],
    subject_t: str | None,
    body_t: str,
    tokens: dict[str, str | None],
    fallbacks: dict[str, str],
    edits: JourneyEdits,
) -> tuple[RenderedTouch | None, str | None]:
    subject, miss1 = substitute(subject_t or "", tokens, fallbacks)
    body, miss2 = substitute(body_t, tokens, fallbacks)
    missing = miss1 + miss2
    if missing:
        return None, f"unresolved_token:{missing[0]}"
    # Every email is signed. An unsigned cold email reads as a circular, and a
    # commercial one owes the reader a postal address and a way to stop
    # (D-060). What is not configured is left out, never invented.
    signature_block = signature()
    signed = f"{body}\n\n{signature_block}" if signature_block.strip("-\n ") else body
    return RenderedTouch(step, _day(step, edits), subject, signed, files), None


def _render_touch1(
    lead: JourneyLead, tokens: dict[str, str | None], edits: JourneyEdits = NO_EDITS
) -> tuple[RenderedTouch | None, str | None]:
    tier = lead.firm.tier

    if tier == "4_NONBILLABLE":
        subject_t, body_t = _template("touch1/tier4.md", edits)
        return _finish(1, ("touch1/tier4.md",), subject_t, body_t, tokens, {}, edits)

    variant = select_touch1_variant(lead.signal)
    if variant is None:
        kind = lead.signal.kind if lead.signal else "none"
        return None, f"no_touch1_variant:{kind}"

    if variant == "1A":
        cms_present = bool(lead.firm.cms_detected)
        base_file = "touch1/1a.md" if cms_present else "touch1/1a_no_cms.md"
        default_middle = "touch1/_middle_1a.md" if cms_present else "touch1/_middle_1a_no_cms.md"
        middle_file = _MIDDLE_FILE_FOR_TIER.get(tier, default_middle)

        _, middle_body_t = _template(middle_file, edits)
        middle_rendered, middle_missing = substitute(middle_body_t, tokens, _CMS_FALLBACK)
        if middle_missing:
            return None, f"unresolved_token:{middle_missing[0]}"

        subject_t, body_t = _template(base_file, edits)
        tokens_with_middle = dict(tokens)
        tokens_with_middle["middle_paragraph"] = middle_rendered
        return _finish(
            1, (base_file, middle_file), subject_t, body_t, tokens_with_middle, _CMS_FALLBACK, edits
        )

    fallbacks = {} if variant == "1F" else _CMS_FALLBACK
    subject_t, body_t = _template(_TOUCH1_FILES[variant], edits)
    return _finish(1, (_TOUCH1_FILES[variant],), subject_t, body_t, tokens, fallbacks, edits)


_TOUCH2_BY_PAIN = {
    "mass_tort_campaign": "touch2/pain_mass_tort.md",
    "review_unreturned_call": "touch2/pain_review.md",
    "cms_implemented": "touch2/pain_cms.md",
}


def _render_touch2(
    lead: JourneyLead, tokens: dict[str, str | None], edits: JourneyEdits = NO_EDITS
) -> tuple[RenderedTouch | None, str | None]:
    """touch2/base.md's subject ("re: your {role} opening") and touch8.md
    are both, as drafted, specifically about a job-posting pain -- neither
    has copy that makes sense for a 1D/1E/1F-driven lead (there is no
    "opening" to follow up on for a mass-tort or review signal). Rather than
    force that copy on a lead it does not fit, or kill the whole 8-touch
    relationship over it, this touch is SKIPPED (like touch 8's closed-
    signal case) whenever {role} did not resolve -- see
    _render_touch8's docstring for the same rule."""
    # Non-job pains get their own touch 2 (written after the renderer surfaced the
    # gap: the drafted touch 2 follows up on "your {role} opening", which a
    # mass-tort, review or new-CMS lead does not have). The review variant keeps
    # rule 3 — it offers the back-office half, not an intake person.
    pain_file = _TOUCH2_BY_PAIN.get(lead.signal.kind) if lead.signal else None
    # Tier 4 (hourly) never gets a records/documents pitch: in an hourly shop that
    # work is billable, and moving it converts revenue into cost — the exact thing
    # the tier-4 holdout exists to test. Only unbillable functions are sellable.
    if pain_file is not None and lead.firm.tier == "4_NONBILLABLE":
        return None, None
    if pain_file is not None:
        subject_t, body_t = _template(pain_file, edits)
        return _finish(2, (pain_file,), subject_t, body_t, tokens, {}, edits)

    if tokens.get("role") is None:
        return None, None

    specific_file = (
        "touch2/_specific_work_1b.md"
        if lead.firm.tier == "1B"
        else "touch2/_specific_work_1a.md"
    )
    _, specific_t = _template(specific_file, edits)
    specific_rendered, specific_missing = substitute(specific_t, tokens, {})
    if specific_missing:
        return None, f"unresolved_token:{specific_missing[0]}"

    subject_t, body_t = _template("touch2/base.md", edits)
    tokens2 = dict(tokens)
    tokens2["specific_work_paragraph"] = specific_rendered
    return _finish(2, ("touch2/base.md", specific_file), subject_t, body_t, tokens2, {}, edits)


def _render_touch3(
    lead: JourneyLead, tokens: dict[str, str | None], edits: JourneyEdits = NO_EDITS
) -> tuple[RenderedTouch | None, str | None]:
    variant = select_touch3_variant(lead.firm.fee_model, lead.firm.tier)
    if variant is None:
        return None, f"fee_model_unresolved:{lead.firm.fee_model}"
    file_name = f"touch3/{variant}.md"
    subject_t, body_t = _template(file_name, edits)
    return _finish(3, (file_name,), subject_t, body_t, tokens, {}, edits)


def _render_touch8(
    lead: JourneyLead, tokens: dict[str, str | None], edits: JourneyEdits = NO_EDITS
) -> tuple[RenderedTouch | None, str | None]:
    """Touch 8 only fires while the arming signal is still open, and only
    when there is a {role}/{days_open} job-posting pain to ask about again
    ("the {role} posting is still up") -- a closed signal, an absent signal,
    or a signal kind with no role in its evidence (1D/1E/1F) all mean the
    touch is silently omitted, not an exclusion reason. The other touches
    are still worth sending."""
    if lead.signal is None or lead.signal.closed_at is not None:
        return None, None
    if tokens.get("role") is None:
        return None, None
    subject_t, body_t = _template("touch8.md", edits)
    return _finish(8, ("touch8.md",), subject_t, body_t, tokens, {}, edits)


def _render_static(
    step: int, tokens: dict[str, str | None], edits: JourneyEdits = NO_EDITS
) -> tuple[RenderedTouch | None, str | None]:
    file_name = _STATIC_TOUCHES[step]
    subject_t, body_t = _template(file_name, edits)
    fallbacks = _CMS_FALLBACK if step == 5 else {}
    return _finish(step, (file_name,), subject_t, body_t, tokens, fallbacks, edits)


def build_journey(lead: JourneyLead, edits: JourneyEdits = NO_EDITS) -> JourneyResult:
    """Render every touch for `lead`'s band, or return an exclusion reason.

    `lead.band` must already be 'SEQUENCE' or 'NURTURE' -- STRIKE (human,
    same day, never rendered) and HOLD (never contacted) are the caller's
    responsibility to filter out before reaching here. `edits` is what the
    Email journey screen changed (D-057); without it, the copy files and
    journey/sequences.yml as they are.
    """
    if lead.band not in ("SEQUENCE", "NURTURE"):
        raise ValueError(f"build_journey: band must be SEQUENCE or NURTURE, got {lead.band!r}")

    band_rules = load_config()["band_rules"]
    has_signal_evidence = lead.signal is not None and bool(lead.signal.evidence)

    if lead.band == "SEQUENCE":
        rules = band_rules["SEQUENCE"]
        if rules.get("requires_signal_evidence") and not has_signal_evidence:
            return JourneyResult([], "sequence_missing_signal_evidence")
        steps = rules["touches"]
        day_multiplier = 1
    else:
        rules = band_rules["NURTURE"]
        steps = (
            rules["touches_with_signal"]
            if has_signal_evidence
            else rules["touches_without_signal"]
        )
        day_multiplier = rules["day_multiplier"]

    tokens = _build_tokens(lead)

    renderers = {1: _render_touch1, 2: _render_touch2, 3: _render_touch3, 8: _render_touch8}
    is_tier4 = lead.firm.tier == "4_NONBILLABLE"

    touches: list[RenderedTouch] = []
    for step in steps:
        renderer = renderers.get(step)
        touch, reason = (
            renderer(lead, tokens, edits) if renderer else _render_static(step, tokens, edits)
        )

        if reason is not None:
            return JourneyResult([], reason)
        if touch is None:
            continue  # touch 8 (or 2) omitted -- sequence continues
        if is_tier4 and step not in (1, 3) and "paralegal" in (touch.subject + touch.body).lower():
            # Touches 1 and 3 are tier 4's own dedicated copy, which names
            # "paralegal" only to decline it -- that is the approved,
            # deliberate framing. Every other touch's copy is shared across
            # tiers (see journey/sequences.yml's tier-swap notes: only 1B's
            # touch 1/2 and 1B/2/3's touch 1 middle paragraph have tier-
            # specific text) and was written for a PI/paralegal context that
            # never fits a tier-4 firm -- e.g. touch 4's "two paralegals" and
            # touch 2's "the paralegal seat" comparable-firm story. Rather
            # than pitch a paralegal indirectly through borrowed copy, the
            # touch is skipped for this tier. This is what structurally
            # guarantees "tier 4 never receives paralegal copy" end to end.
            continue
        if day_multiplier != 1:
            touch = RenderedTouch(
                touch.step, touch.day * day_multiplier, touch.subject, touch.body, touch.templates
            )
        touches.append(touch)

    if not touches:
        return JourneyResult([], "no_touches_rendered")

    # Tier 4_NONBILLABLE's paralegal ban is structural, not a text scan: the
    # `tier == "4_NONBILLABLE"` branches in `_render_touch1`/`_render_touch3`
    # above always select the dedicated tier-4 copy (touch1/tier4.md,
    # touch3/hourly.md) instead of a role-based pain variant, regardless of
    # which signal armed the lead. A substring ban on the word "paralegal"
    # would be wrong here -- tier 4's own approved copy names it deliberately
    # ("I'm not going to suggest a paralegal") to preempt the objection.
    # See tests/journey/test_build.py::test_tier4_never_selects_role_variant.

    return JourneyResult(touches, None)
