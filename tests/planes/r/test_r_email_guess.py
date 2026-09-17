"""r_email_guess: the candidate addresses a name and a domain give, most
common first; the verifier tried on each until one is real; a catch-all
domain stops the spending; an attempt already paid for is read back, never
bought again. A fake adapter answers; nothing reaches a provider."""

from __future__ import annotations

import uuid

import pytest

from lge.planes.r import r4_verify, r_email_guess
from lge.planes.r.r4_verify import VerifyError, VerifyResult
from lge.registry import RunContext
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db


def _ctx(conn) -> RunContext:
    return RunContext(conn, get_settings())


def _person(conn, firm_id, full_name="John Smith", role="owner", confidence=0.9) -> str:
    cid = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO contact (id, firm_id, full_name, role, confidence) "
            "VALUES (%s, %s, %s, %s, %s)",
            (cid, firm_id, full_name, role, confidence),
        )
    return cid


def _emails(conn, contact_id) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT email, status, pattern, verified_at FROM contact_email WHERE contact_id = %s",
            (contact_id,),
        )
        return cur.fetchall()


def _attempts(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT email, provider, result, cost_usd FROM verify_attempt ORDER BY id")
        return cur.fetchall()


class Fake:
    """Answers per address; remembers what it was asked."""

    def __init__(self, answers: dict[str, str], default: str = "invalid") -> None:
        self.answers = answers
        self.default = default
        self.asked: list[str] = []

    def __call__(self, email, *, client, api_key, cfg):
        self.asked.append(email)
        status = self.answers.get(email, self.default)
        if status == "boom":
            raise VerifyError("timeout after 2 attempt(s)")
        return VerifyResult(status, {"email": email, "status": status})


@pytest.fixture
def fake(monkeypatch):
    def install(answers: dict[str, str], default: str = "invalid") -> Fake:
        f = Fake(answers, default)
        monkeypatch.setitem(r4_verify._ADAPTERS, "fake", f)
        monkeypatch.setattr(r_email_guess, "_price", lambda cfg, provider: 0.01)
        return f

    return install


def test_candidates_are_the_schemes_most_common_first_without_duplicates():
    got = r_email_guess.candidates("John A. Smith", "smithlaw.com")
    assert [a for _s, a in got][:4] == [
        "john.smith@smithlaw.com", "john@smithlaw.com", "jsmith@smithlaw.com",
        "johnsmith@smithlaw.com",
    ]
    assert len(got) == 11 and len({a for _s, a in got}) == 11
    assert r_email_guess.candidates("Madonna", "x.com") == []  # no first+last pair


def test_the_third_candidate_is_the_real_one(db, fake):
    firm_id = make_firm(db, tier="1A", domain="smithlaw.com")
    owner = _person(db, firm_id)
    f = fake({"jsmith@smithlaw.com": "valid"})

    result = r_email_guess.run(_ctx(db), provider="fake")
    assert result.processed == 1 and result.failed == 0, result.notes
    assert f.asked == ["john.smith@smithlaw.com", "john@smithlaw.com", "jsmith@smithlaw.com"]
    rows = _emails(db, owner)
    assert [(r["email"], r["status"], r["pattern"]) for r in rows] == [
        ("jsmith@smithlaw.com", "valid", "flast")
    ]
    assert rows[0]["verified_at"] is not None
    assert [(a["result"], float(a["cost_usd"])) for a in _attempts(db)] == [
        ("invalid", 0.01), ("invalid", 0.01), ("valid", 0.01)
    ]
    assert "addresses confirmed 1" in result.notes[0] and "spent $0.03" in result.notes[0]

    # a second run finds nobody left to ask
    again = r_email_guess.run(_ctx(db), provider="fake")
    assert again.processed == 0 and len(f.asked) == 3


def test_a_catch_all_domain_stops_the_spending_for_the_whole_firm(db, fake):
    firm_id = make_firm(db, tier="1A", domain="catchall.law")
    owner = _person(db, firm_id, "Ann Lee", role="owner")
    admin = _person(db, firm_id, "Bob Roe", role="admin", confidence=0.5)
    f = fake({}, default="catch_all")

    result = r_email_guess.run(_ctx(db), provider="fake")
    assert result.processed == 2
    assert f.asked == ["ann.lee@catchall.law"]  # one call told us everything
    assert [(r["email"], r["status"]) for r in _emails(db, owner)] == [
        ("ann.lee@catchall.law", "catch_all")
    ]
    assert [(r["email"], r["status"]) for r in _emails(db, admin)] == [
        ("bob.roe@catchall.law", "catch_all")
    ]
    assert "catch-all domains 1 (2 people)" in result.notes[0]


def test_an_attempt_already_paid_for_is_read_back_not_bought_again(db, fake):
    firm_id = make_firm(db, tier="1A", domain="paid.law")
    owner = _person(db, firm_id, "Jane Doe")
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO verify_attempt (email, provider, result, raw, cost_usd) VALUES "
            "('jane.doe@paid.law', 'fake', 'invalid', '{}', 0.01), "
            "('jane@paid.law', 'fake', 'valid', '{}', 0.01)"
        )
    f = fake({})
    result = r_email_guess.run(_ctx(db), provider="fake")
    assert result.processed == 1 and f.asked == []
    assert [(r["email"], r["status"]) for r in _emails(db, owner)] == [("jane@paid.law", "valid")]


def test_selection_is_tier_gated_and_leaves_pattern_firms_to_r3(db, fake):
    dq = make_firm(db, tier="DQ_SIZE", domain="dq.law")
    _person(db, dq)
    untiered = make_firm(db, tier=None, domain="untiered.law")
    _person(db, untiered)
    patterned = make_firm(db, tier="1A", domain="known.law")
    known = _person(db, patterned, "Kay Known")
    with db.cursor() as cur:  # one on-domain address exists: r3 learns the pattern, not us
        cur.execute("INSERT INTO contact_email (contact_id, email, status) VALUES (%s, %s, %s)",
                    (known, "kay@known.law", "unverified"))
    _person(db, patterned, "Lee Missing", role="admin")
    attorney_only = make_firm(db, tier="1A", domain="atty.law")
    _person(db, attorney_only, "Sam Atty", role="attorney")

    f = fake({})
    result = r_email_guess.run(_ctx(db), provider="fake")
    assert result.processed == 0 and result.skipped == 0 and f.asked == []


def test_budget_stop_and_a_dead_verifier(db, fake):
    firm_id = make_firm(db, tier="1A", domain="budget.law")
    _person(db, firm_id, "Al Aa")
    _person(db, firm_id, "Bo Bb", role="admin")
    fake({})
    result = r_email_guess.run(_ctx(db), provider="fake", max_usd="0.02", max_candidates="6")
    assert any("budget stop" in n for n in result.notes)
    assert len(_attempts(db)) == 2  # two cents, then stop

    firm2 = make_firm(db, tier="1A", domain="dead.law")
    owner = _person(db, firm2, "Di Dd")
    fake({}, default="boom")
    result = r_email_guess.run(_ctx(db), provider="fake")
    # the two people the budget stopped are still waiting, plus the new one:
    # a dead verifier fails each of them, and nothing is written for anyone
    assert result.failed == 3 and result.processed == 0 and _emails(db, owner) == []


def test_inert_without_a_verifier(db):
    firm_id = make_firm(db, tier="1A", domain="quiet.law")
    _person(db, firm_id)
    result = r_email_guess.run(_ctx(db))  # conftest pins LGE_EMAIL_VERIFIER=none
    assert result.skipped == 1 and result.processed == 0
    assert any("inert" in n for n in result.notes)
