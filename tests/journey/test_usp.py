"""The offer paragraph and the call to action every drafted email carries
(D-070): Legal Soft's own numbers, chosen by the pain, rotated by the
email, never repeating the copy, never a banned phrase; and one link."""

from __future__ import annotations

from datetime import UTC, datetime

from lge.journey import usp
from lge.journey.build import build_journey
from lge.journey.model import Contact, Firm, JourneyLead, Signal
from lge.journey.select import scan_banned

_AT = datetime(2026, 9, 30, tzinfo=UTC)


def _review_lead(tier: str = "1B") -> JourneyLead:
    return JourneyLead(
        lead_id="l1", band="SEQUENCE",
        firm=Firm(id="f1", canonical_name="The Duron Law Firm, PC", city="Chicago", state="IL",
                  tier=tier, fee_model="flat", primary_practice="immigration", cms_detected=None),
        contact=Contact(id="c1", full_name="Andrea Duron", title="Owner", role="owner"),
        signal=Signal(id=1, kind="review_unreturned_call", first_seen=_AT, last_seen=_AT,
                      closed_at=None, repost_count=0, evidence={"reviews": 6}),
        repost_first_seen=None, at=_AT,
    )


def test_every_email_carries_the_offer_a_number_and_the_call_to_action():
    result = build_journey(_review_lead())
    assert result.excluded_reason is None and len(result.touches) >= 7
    for t in result.touches:
        assert t.usp and t.usp in t.body, t.step
        assert any(ch.isdigit() for ch in t.usp), (t.step, t.usp)  # a number, every time
        assert t.cta and t.cta in t.body, t.step
        assert "https://www.legalsoft.com/contact-us" in t.cta
        assert t.body.index(t.usp) < t.body.index(t.cta)  # offer, then the ask
        assert scan_banned(t.usp + " " + t.cta) == [], t.step


def test_the_offer_answers_the_pain_and_names_the_right_people():
    touches = {t.step: t for t in build_journey(_review_lead("1B")).touches}
    first = touches[1].usp
    assert first.startswith("Legal Soft's bilingual intake specialists ")
    assert "Someone is on your phones while you are in court or with a client." in first
    assert "every call" not in first.lower()  # what the person is for, never a guarantee
    # The pain is why we write, never what we say.
    for t in touches.values():
        low = t.body.lower()
        assert "review" not in t.usp.lower() and "1-star" not in low and "complain" not in low
    other = {t.step: t for t in build_journey(_review_lead("3")).touches}
    assert other[1].usp.startswith("Legal Soft's intake specialists ")


def test_the_emails_do_not_all_make_the_same_case():
    touches = build_journey(_review_lead()).touches
    assert len({t.usp for t in touches}) >= 5
    by_step = {t.step: t.usp for t in touches}
    assert "40% increase in profits" in by_step[3] and "60%" in by_step[3]  # the arithmetic
    assert "1,000 law firms" in by_step[4]  # the comparable firm


def test_a_fact_the_copy_already_states_is_not_said_twice():
    # hard-wrapped, as the copy files are: "three\ndays" is still "three days"
    body = "They're pre-vetted, they work your hours, and one can start in under three\ndays."
    picked = usp.pick_facts(1, body)
    assert "speed" not in picked and "vetted" not in picked
    assert picked[:2] == ["exclusive", "saving"]
    assert usp.pick_facts(1, "Nothing said yet.")[:1] == ["speed"]


def test_no_link_no_call_to_action_and_the_button_escapes_its_text():
    assert usp.cta_block({"cta": {"label": "Book a call", "url": ""}}) == ""
    assert usp.cta_missing({"cta": {"url": ""}}) == ["a link for the call to action"]
    cfg = {"cta": {"label": 'Book a "call" <now>', "url": "https://x.example/a?b=1&c=2",
                   "reply": "Or reply."}}
    assert usp.cta_block(cfg) == 'Book a "call" <now>: https://x.example/a?b=1&c=2\nOr reply.'
    button = usp.cta_html(cfg)
    assert 'href="https://x.example/a?b=1&amp;c=2"' in button
    assert "&lt;now&gt;" in button and "<now>" not in button


def test_switched_off_the_emails_are_the_copy_alone():
    cfg = {**usp.load_usp(), "enabled": False}
    assert usp.usp_paragraph(1, "x", pain="review_unreturned_call", tier="1B", cfg=cfg) == ""
