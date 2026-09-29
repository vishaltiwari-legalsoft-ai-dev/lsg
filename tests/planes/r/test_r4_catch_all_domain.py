"""One catch-all answer settles a whole domain: the rest of its candidates are
marked catch-all without a paid call, in this run and in later runs."""

import httpx
import respx

from lge.planes.r import r4_verify
from tests.planes.r.test_r4_verify import (
    _ctx,
    _email_status,
    _insert_contact_with_email,
    make_firm,
)


@respx.mock
def test_first_catch_all_answer_settles_the_domain(db, monkeypatch):
    monkeypatch.setenv("NEVERBOUNCE_API_KEY", "test-key")
    firm_id = make_firm(db, tier="1A")
    c1, e1 = _insert_contact_with_email(db, firm_id, role="owner", email="a.one@acme.com")
    c2, e2 = _insert_contact_with_email(db, firm_id, role="owner", email="b.two@acme.com")
    c3, e3 = _insert_contact_with_email(db, firm_id, role="admin", email="c.three@acme.com")
    route = respx.post(r4_verify._NEVERBOUNCE_URL).mock(
        return_value=httpx.Response(200, json={"status": "success", "result": "catchall"})
    )

    result = r4_verify.run(_ctx(db), provider="neverbounce")

    assert route.call_count == 1  # one paid call, not three
    assert result.processed == 3
    assert {_email_status(db, c, e) for c, e in ((c1, e1), (c2, e2), (c3, e3))} == {"catch_all"}
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM verify_attempt WHERE email LIKE '%%@acme.com'")
        assert cur.fetchone()["n"] == 1

    # A later run at the same domain pays nothing either.
    c4, e4 = _insert_contact_with_email(db, firm_id, role="owner", email="d.four@acme.com")
    result2 = r4_verify.run(_ctx(db), provider="neverbounce")
    assert route.call_count == 1
    assert _email_status(db, c4, e4) == "catch_all"
    assert result2.processed == 1
