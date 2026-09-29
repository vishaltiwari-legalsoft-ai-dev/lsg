"""A provider's "unknown" is not a verdict: the address stays unverified,
nothing is billed, and it is asked again after a week, twice at most
(readiness audit, 28 Sep 2026, finding 15)."""

from __future__ import annotations

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
def test_unknown_stays_unverified_and_is_asked_again_later(db, monkeypatch):
    monkeypatch.setenv("NEVERBOUNCE_API_KEY", "test-key")
    firm_id = make_firm(db, tier="1A")
    contact_id, email = _insert_contact_with_email(db, firm_id, role="owner", email="u@acme.com")
    route = respx.post(r4_verify._NEVERBOUNCE_URL).mock(
        return_value=httpx.Response(200, json={"status": "success", "result": "unknown"})
    )

    first = r4_verify.run(_ctx(db), provider="neverbounce")
    assert route.call_count == 1 and first.processed == 1
    assert _email_status(db, contact_id, email) == "unverified"
    with db.cursor() as cur:
        cur.execute("SELECT result, cost_usd FROM verify_attempt WHERE email = %s", (email,))
        rows = cur.fetchall()
    assert [(r["result"], float(r["cost_usd"])) for r in rows] == [("unknown", 0.0)]

    # The same week: not asked again.
    second = r4_verify.run(_ctx(db), provider="neverbounce")
    assert route.call_count == 1 and second.skipped == 1

    # A week later: asked once more ...
    with db.cursor() as cur:
        cur.execute("UPDATE verify_attempt SET created_at = now() - interval '8 days' "
                    "WHERE email = %s", (email,))
    r4_verify.run(_ctx(db), provider="neverbounce")
    assert route.call_count == 2

    # ... and after two unknowns it is left alone for good.
    with db.cursor() as cur:
        cur.execute("UPDATE verify_attempt SET created_at = now() - interval '30 days' "
                    "WHERE email = %s", (email,))
    r4_verify.run(_ctx(db), provider="neverbounce")
    assert route.call_count == 2
    assert _email_status(db, contact_id, email) == "unverified"
