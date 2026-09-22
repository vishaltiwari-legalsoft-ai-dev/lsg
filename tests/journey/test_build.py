"""build_journey: the full renderer. No DB -- JourneyLead is built by hand
here; lge/export/list.py is what wires real rows into it (see
tests/export/test_list.py for the DB-backed hygiene tests)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from lge.journey.build import build_journey
from lge.journey.model import Contact, Firm, JourneyLead, Signal
from lge.journey.render import COPY_ROOT
from lge.journey.select import scan_banned

_AT = datetime(2026, 9, 11, tzinfo=UTC)


def _email(touch) -> str:
    """The email itself. Every rendered email carries the signature block
    (D-060); test_every_email_is_signed owns that part."""
    from lge.journey.render import signature

    block = signature()
    if block and block in touch.body:
        return touch.body[: touch.body.index(block)].rstrip("\n")
    return touch.body


def _firm(**kw) -> Firm:
    defaults = dict(
        id="f1",
        canonical_name="Acme Law",
        city="Austin",
        state="TX",
        tier="1A",
        fee_model="contingency",
        primary_practice="personal_injury",
        cms_detected="filevine",
    )
    defaults.update(kw)
    return Firm(**defaults)


def _contact(**kw) -> Contact:
    defaults = dict(id="c1", full_name="Jane Doe", title="Owner", role="owner")
    defaults.update(kw)
    return Contact(**defaults)


def _signal(**kw) -> Signal:
    defaults = dict(
        id=1,
        kind="job_posting_open",
        first_seen=datetime(2026, 8, 14, tzinfo=UTC),
        last_seen=_AT,
        closed_at=None,
        repost_count=0,
        evidence={"title": "Paralegal", "canonical_role": "demand_writer"},
    )
    defaults.update(kw)
    return Signal(**defaults)


def _lead(**kw) -> JourneyLead:
    defaults = dict(
        lead_id="l1",
        band="SEQUENCE",
        firm=_firm(),
        contact=_contact(),
        signal=_signal(),
        repost_first_seen=None,
        at=_AT,
    )
    defaults.update(kw)
    return JourneyLead(**defaults)


# ---------------------------------------------------------------------------
# Faithful transcription: the rendered tier-1A touch 1 must match
# plan/email-drafts.md's 1A draft exactly after token substitution.
# ---------------------------------------------------------------------------


def test_rendered_1a_matches_plan_email_drafts_exactly():
    lead = _lead(
        contact=_contact(full_name="John Smith"),
        signal=_signal(evidence={"title": "Paralegal", "canonical_role": "demand_writer"}),
    )
    result = build_journey(lead)
    assert result.excluded_reason is None
    touch1 = result.touches[0]

    assert touch1.subject == "Your demand writer opening, and a faster way to fill it"
    assert _email(touch1) == (
        "Hi John,\n"
        "\n"
        "Your demand writer post has been up since 14 August. When a seat stays open\n"
        "that long it's usually the local market rather than the offer, and another\n"
        "month of the same search rarely changes it.\n"
        "\n"
        "We place trained legal staff with personal injury firms: one person,\n"
        "dedicated to your cases, working inside Filevine. Not a pooled service desk,\n"
        "and not a temp.\n"
        "\n"
        "Every candidate is pre-vetted and trained on firm work before you meet\n"
        "them. Interviewing costs nothing, and someone who fits can start in under\n"
        "three days.\n"
        "\n"
        "If it would help, I'll send two profiles matched to that seat. No\n"
        "obligation either way."
    )


def test_rendered_1a_no_cms_matches_plan_email_drafts_exactly():
    lead = _lead(
        contact=_contact(full_name="John Smith"),
        firm=_firm(cms_detected=None),
        signal=_signal(evidence={"title": "Paralegal", "canonical_role": "demand_writer"}),
    )
    result = build_journey(lead)
    assert result.excluded_reason is None
    touch1 = result.touches[0]
    assert _email(touch1) == (
        "Hi John,\n"
        "\n"
        "Your demand writer post has been up since 14 August. When a seat stays open\n"
        "that long it's usually the local market rather than the offer, and another\n"
        "month of the same search rarely changes it.\n"
        "\n"
        "We place trained legal staff with personal injury firms: one person,\n"
        "dedicated to your cases, working in your own systems. Not a pooled service\n"
        "desk, and not a temp.\n"
        "\n"
        "Every candidate is pre-vetted and trained on firm work before you meet\n"
        "them. Interviewing costs nothing, and someone who fits can start in under\n"
        "three days.\n"
        "\n"
        "If it would help, I'll send two profiles matched to that seat. No\n"
        "obligation either way."
    )


def test_full_sequence_has_nine_touches_in_day_order():
    result = build_journey(_lead())
    assert result.excluded_reason is None
    assert [t.step for t in result.touches] == list(range(1, 10))
    assert [t.day for t in result.touches] == [0, 3, 7, 10, 14, 18, 21, 25, 28]


# ---------------------------------------------------------------------------
# Token resolution -> exclusion
# ---------------------------------------------------------------------------


def test_missing_first_name_excludes_lead():
    lead = _lead(contact=_contact(full_name="Mr. Smith"))
    result = build_journey(lead)
    assert result.excluded_reason == "unresolved_token:first_name"
    assert result.touches == []


def test_smith_john_comma_format_resolves():
    lead = _lead(contact=_contact(full_name="Smith, John"))
    result = build_journey(lead)
    assert result.excluded_reason is None
    assert result.touches[0].body.startswith("Hi John,")


def test_sequence_without_signal_evidence_is_excluded():
    lead = _lead(band="SEQUENCE", signal=None)
    result = build_journey(lead)
    assert result.excluded_reason == "sequence_missing_signal_evidence"


def test_sequence_with_empty_evidence_dict_is_excluded():
    lead = _lead(signal=_signal(evidence={}))
    result = build_journey(lead)
    assert result.excluded_reason == "sequence_missing_signal_evidence"


def test_unmapped_signal_kind_excludes_sequence_lead():
    lead = _lead(signal=_signal(kind="partner_intro", evidence={"q": "warm intro"}))
    result = build_journey(lead)
    assert result.excluded_reason == "no_touch1_variant:partner_intro"


# ---------------------------------------------------------------------------
# Variant selection per signal kind
# ---------------------------------------------------------------------------


def test_repost_selects_1b_and_resolves_repost_month():
    lead = _lead(
        signal=_signal(
            kind="job_posting_open",
            repost_count=1,
            evidence={"title": "Paralegal", "canonical_role": "paralegal"},
        ),
        repost_first_seen=date(2026, 5, 3),
    )
    result = build_journey(lead)
    assert result.excluded_reason is None
    touch1 = result.touches[0]
    assert touch1.subject == "The paralegal role at your firm, posted a second time"
    assert "the second time since May" in " ".join(touch1.body.split())


def test_repost_without_repost_first_seen_excludes_lead():
    # repost_count >= 1 but no signal_sighting proved the repost date --
    # {repost_month} genuinely cannot resolve.
    lead = _lead(
        signal=_signal(kind="job_posting_open", repost_count=1),
        repost_first_seen=None,
    )
    result = build_journey(lead)
    assert result.excluded_reason == "unresolved_token:repost_month"


def test_multi_opening_selects_1c_with_both_roles():
    lead = _lead(
        signal=_signal(
            kind="multi_opening",
            evidence={
                "roles": [
                    {"title": "Legal Assistant", "canonical_role": "legal_assistant"},
                    {"title": "Paralegal", "canonical_role": "paralegal"},
                ]
            },
        )
    )
    result = build_journey(lead)
    assert result.excluded_reason is None
    touch1 = result.touches[0]
    assert touch1.subject == "Two seats open at Acme Law, which one first?"
    assert "a legal assistant and a paralegal posted at the same time" in touch1.body


def test_multi_opening_missing_second_role_excludes_lead():
    lead = _lead(
        signal=_signal(
            kind="multi_opening",
            evidence={"roles": [{"title": "Legal Assistant", "canonical_role": "legal_assistant"}]},
        )
    )
    result = build_journey(lead)
    assert result.excluded_reason == "unresolved_token:role_2"


def test_mass_tort_selects_1d_with_tort_token():
    lead = _lead(
        signal=_signal(kind="mass_tort_campaign", evidence={"tort": "Camp Lejeune"}),
    )
    result = build_journey(lead)
    assert result.excluded_reason is None
    touch1 = result.touches[0]
    assert touch1.subject == "Camp Lejeune intake, and the records volume behind it"
    assert "you're running Camp Lejeune intake" in touch1.body
    # touch 2 and touch 8 are both specifically about a job-posting pain
    # ("re: your {role} opening" / "the {role} posting is still up") --
    # mass-tort evidence carries no {role}, so both are skipped rather than
    # excluding the whole lead. See journey/sequences.yml's decision note.
    assert [t.step for t in result.touches] == [1, 2, 3, 4, 5, 6, 7, 9]
    # touch 2 is the pain-specific follow-up, not the job-posting one
    touch2 = result.touches[1]
    assert touch2.subject == "Re: Camp Lejeune, and who chases the providers"
    assert "opening" not in touch2.body


def test_review_signal_selects_1e_and_never_quotes_the_review():
    lead = _lead(
        firm=_firm(primary_practice="personal_injury"),
        signal=_signal(
            kind="review_unreturned_call",
            evidence={"quote": "nobody ever called me back, terrible firm"},
        ),
    )
    result = build_journey(lead)
    assert result.excluded_reason is None
    touch1 = result.touches[0]
    assert touch1.subject == "Intake coverage at Acme Law"
    assert "personal injury" in " ".join(touch1.body.split())
    full_text = touch1.subject + touch1.body
    assert "terrible" not in full_text.lower()
    assert "nobody ever called me back" not in full_text
    # review evidence carries no {role} either -- same touch 2/8 skip.
    assert [t.step for t in result.touches] == [1, 2, 3, 4, 5, 6, 7, 9]
    # touch 2 offers the back-office half (rule 3: open on a role that touches
    # no client) and stays practice-neutral (the review signal also runs for 1B)
    touch2 = result.touches[1]
    assert touch2.subject == "Re: intake coverage, and the half you can hand over"
    assert "back-office half" in " ".join(touch2.body.split())
    assert "demand" not in touch2.body.lower()
    assert "nobody ever called me back" not in touch2.body


def test_cms_implemented_selects_1f_requires_cms():
    lead = _lead(
        firm=_firm(cms_detected="mycase"),
        signal=_signal(kind="cms_implemented", evidence={"title": "moved to MyCase"}),
    )
    result = build_journey(lead)
    assert result.excluded_reason is None
    touch1 = result.touches[0]
    assert touch1.subject == "Now that you're on MyCase"


def test_cms_implemented_without_cms_excludes_lead():
    lead = _lead(
        firm=_firm(cms_detected=None),
        signal=_signal(kind="cms_implemented", evidence={"title": "moved to a new CMS"}),
    )
    result = build_journey(lead)
    assert result.excluded_reason == "unresolved_token:cms"


def test_no_cms_falls_back_to_your_systems_outside_1a_and_1f():
    lead = _lead(
        firm=_firm(cms_detected=None),
        signal=_signal(
            kind="multi_opening",
            evidence={
                "roles": [
                    {"title": "Legal Assistant", "canonical_role": "legal_assistant"},
                    {"title": "Paralegal", "canonical_role": "paralegal"},
                ]
            },
        ),
    )
    result = build_journey(lead)
    assert result.excluded_reason is None
    assert "working inside your systems" in " ".join(result.touches[0].body.split())


# ---------------------------------------------------------------------------
# Touch 3: fee model variants, tier 3's swapped closing
# ---------------------------------------------------------------------------


def test_touch3_contingency():
    result = build_journey(_lead(firm=_firm(tier="1A", fee_model="contingency")))
    touch3 = next(t for t in result.touches if t.step == 3)
    assert touch3.subject == "The unbilled hours between you and the fee"
    assert "A demand writer isn't a saving" in " ".join(touch3.body.split())


def test_touch3_fee_shifting():
    lead = _lead(
        firm=_firm(tier="2", fee_model="fee_shifting", primary_practice="employment"),
        signal=_signal(kind="multi_opening", evidence={
            "roles": [
                {"title": "Case Manager", "canonical_role": "case_manager"},
                {"title": "Legal Assistant", "canonical_role": "legal_assistant"},
            ]
        }),
    )
    result = build_journey(lead)
    touch3 = next(t for t in result.touches if t.step == 3)
    assert touch3.subject == "Who actually pays for those hours"
    assert "The defendant pays the fees" in " ".join(touch3.body.split())


def test_touch3_flat_tier_1b():
    lead = _lead(
        firm=_firm(tier="1B", fee_model="flat", primary_practice="immigration"),
        signal=_signal(evidence={"title": "Legal Assistant", "canonical_role": "legal_assistant"}),
    )
    result = build_journey(lead)
    touch3 = next(t for t in result.touches if t.step == 3)
    assert "you'll see the effect on the next twenty" in " ".join(touch3.body.split())


def test_touch3_flat_tier_3_has_swapped_closing():
    lead = _lead(
        firm=_firm(tier="3", fee_model="flat", primary_practice="bankruptcy"),
        signal=_signal(evidence={"title": "Legal Assistant", "canonical_role": "legal_assistant"}),
    )
    result = build_journey(lead)
    touch3 = next(t for t in result.touches if t.step == 3)
    assert touch3.subject == "Margin, one matter at a time"
    assert "Thin margins and a lot of matters" in " ".join(touch3.body.split())
    assert "next twenty cases" not in touch3.body


def test_touch3_hourly():
    lead = _lead(firm=_firm(tier="4_NONBILLABLE", fee_model="hourly", primary_practice="business"))
    result = build_journey(lead)
    touch3 = next(t for t in result.touches if t.step == 3)
    assert touch3.subject == "Only the part nobody bills"


@pytest.mark.parametrize("fee_model", [None, "mixed", "unknown"])
def test_touch3_unresolved_fee_model_excludes_lead(fee_model):
    lead = _lead(firm=_firm(fee_model=fee_model))
    result = build_journey(lead)
    assert result.excluded_reason == f"fee_model_unresolved:{fee_model}"


# ---------------------------------------------------------------------------
# Tier swaps (touch 1 middle paragraph / touch 2 specific-work paragraph)
# ---------------------------------------------------------------------------


def test_tier_1b_middle_paragraph_swap():
    lead = _lead(
        firm=_firm(
            tier="1B", fee_model="flat", primary_practice="immigration", cms_detected="clio"
        ),
        signal=_signal(
            evidence={"title": "Legal Assistant", "canonical_role": "legal_assistant_es"}
        ),
    )
    result = build_journey(lead)
    touch1 = result.touches[0]
    assert "bilingual legal assistants with immigration firms" in " ".join(touch1.body.split())
    assert "PI firms" not in touch1.body


def test_tier_2_middle_paragraph_swap_uses_practice_token():
    lead = _lead(
        firm=_firm(
            tier="2", fee_model="fee_shifting", primary_practice="employment", cms_detected="clio"
        ),
        signal=_signal(evidence={"title": "Case Manager", "canonical_role": "case_manager"}),
    )
    result = build_journey(lead)
    touch1 = result.touches[0]
    assert "case managers with employment firms" in " ".join(touch1.body.split())


def test_tier_2_touch2_uses_base_tier1a_paragraph_known_gap():
    # No tier-2-specific touch-2 copy exists in plan/email-drafts.md -- the
    # base (tier-1A) "records chase" paragraph carries across unchanged.
    # This is a documented content gap, not a renderer bug.
    lead = _lead(
        firm=_firm(tier="2", fee_model="fee_shifting", primary_practice="employment"),
    )
    result = build_journey(lead)
    touch2 = next(t for t in result.touches if t.step == 2)
    assert "records chase" in " ".join(touch2.body.split())


def test_tier_1b_touch2_swap():
    lead = _lead(
        firm=_firm(tier="1B", fee_model="flat", primary_practice="immigration"),
        signal=_signal(
            evidence={"title": "Legal Assistant", "canonical_role": "legal_assistant_es"}
        ),
    )
    result = build_journey(lead)
    touch2 = next(t for t in result.touches if t.step == 2)
    assert "form preparation at volume" in touch2.body


# ---------------------------------------------------------------------------
# Tier 4_NONBILLABLE structural guard: never a role-based pain variant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,evidence",
    [
        ("job_posting_open", {"title": "Paralegal", "canonical_role": "paralegal"}),
        (
            "multi_opening",
            {
                "roles": [
                    {"title": "Paralegal", "canonical_role": "paralegal"},
                    {"title": "Legal Assistant", "canonical_role": "legal_assistant"},
                ]
            },
        ),
        ("mass_tort_campaign", {"tort": "Camp Lejeune"}),
        ("review_unreturned_call", {"quote": "never called back"}),
        ("cms_implemented", {"title": "moved to Clio"}),
    ],
)
def test_tier4_never_selects_role_variant(kind, evidence):
    lead = _lead(
        firm=_firm(tier="4_NONBILLABLE", fee_model="hourly", primary_practice="business"),
        signal=_signal(kind=kind, evidence=evidence),
    )
    result = build_journey(lead)
    assert result.excluded_reason is None
    touch1 = result.touches[0]
    assert touch1.subject == "The hours nobody at your firm can bill"
    assert "narrower note than the one you usually get" in touch1.body
    # touches 2, 4 and 8 all carry PI/paralegal-specific copy shared with
    # tier 1A (no tier-4 alternative exists) -- they are skipped for this
    # tier rather than pitching a paralegal indirectly. See build_journey's
    # tier-4 filter. The result is the same reduced set regardless of which
    # signal armed the lead.
    assert [t.step for t in result.touches] == [1, 3, 5, 6, 7, 9]
    # every "paralegal" mention across the whole sequence is touch 1's own
    # deliberate decline -- nowhere else in the sequence names it.
    mentions = [t.step for t in result.touches if "paralegal" in (t.subject + t.body).lower()]
    assert mentions == [1]


def test_tier4_touch1_names_paralegal_only_to_decline_it():
    # The approved copy deliberately names the word to preempt the
    # objection -- this is not a banned-phrase violation.
    lead = _lead(firm=_firm(tier="4_NONBILLABLE", fee_model="hourly", primary_practice="business"))
    result = build_journey(lead)
    touch1 = result.touches[0]
    assert "not going to suggest a paralegal" in " ".join(touch1.body.split())


# ---------------------------------------------------------------------------
# Touch 8 gating
# ---------------------------------------------------------------------------


def test_touch8_present_when_signal_open():
    result = build_journey(_lead(signal=_signal(closed_at=None)))
    assert 8 in [t.step for t in result.touches]


def test_touch8_omitted_when_signal_closed():
    result = build_journey(_lead(signal=_signal(closed_at=_AT)))
    steps = [t.step for t in result.touches]
    assert 8 not in steps
    # the rest of the sequence still runs
    assert steps == [1, 2, 3, 4, 5, 6, 7, 9]


# ---------------------------------------------------------------------------
# Band rules: STRIKE/HOLD never render; NURTURE reduced touches + cadence
# ---------------------------------------------------------------------------


def test_strike_and_hold_are_rejected_by_build_journey():
    with pytest.raises(ValueError):
        build_journey(_lead(band="STRIKE"))
    with pytest.raises(ValueError):
        build_journey(_lead(band="HOLD"))


def test_nurture_with_signal_gets_touches_1_3_9_at_half_cadence():
    result = build_journey(_lead(band="NURTURE"))
    assert result.excluded_reason is None
    assert [(t.step, t.day) for t in result.touches] == [(1, 0), (3, 14), (9, 56)]


def test_nurture_without_signal_skips_touch1_gets_3_9():
    result = build_journey(_lead(band="NURTURE", signal=None))
    assert result.excluded_reason is None
    assert [(t.step, t.day) for t in result.touches] == [(3, 14), (9, 56)]


# ---------------------------------------------------------------------------
# Banned framing -- scan every copy file on disk, and the full rendered 1A.
# ---------------------------------------------------------------------------


def test_no_banned_phrase_in_any_copy_file():
    md_files = sorted(COPY_ROOT.rglob("*.md"))
    assert len(md_files) > 10  # sanity: the copy set actually exists
    offenders = {}
    for path in md_files:
        hits = scan_banned(path.read_text(encoding="utf-8"))
        if hits:
            offenders[str(path.relative_to(COPY_ROOT))] = hits
    assert offenders == {}


def test_no_banned_phrase_in_rendered_sequence():
    result = build_journey(_lead())
    assert result.excluded_reason is None
    for touch in result.touches:
        assert scan_banned(touch.subject) == []
        assert scan_banned(touch.body) == []



def test_every_email_is_signed_and_says_how_to_stop():
    """An unsigned cold email reads as a circular, and a commercial one owes
    the reader a way to stop (D-060). The postal address is configured, never
    invented: `sender_missing` is what tells a person it is still blank."""
    from lge.journey.render import sender_missing, signature

    result = build_journey(_lead())
    assert result.excluded_reason is None
    for touch in result.touches:
        assert touch.body.endswith(signature()), touch.step
        assert "Legal Soft" in touch.body
        assert "stop" in touch.body.lower()
    assert "a postal address, which US law requires" in sender_missing()
