"""The day's ceiling on paid searches is read from search_log, so it holds
across threads and restarts (security review, 28 Sep 2026)."""

from __future__ import annotations

import pytest

from lge.search import daily_cap_refusal
from lge.settings import Settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db


def _serper() -> Settings:
    return Settings(dsn="", admin_dsn="", object_store=".", user_agent="", anthropic_api_key="",
                    openrouter_api_key="", live=False, serper_api_key="k")


def test_the_cap_counts_todays_logged_searches(db):
    firm_id = make_firm(db)
    assert daily_cap_refusal(db, {"daily_cap": "2"}, _serper()) is None
    with db.cursor() as cur:
        for _ in range(2):
            cur.execute(
                "INSERT INTO search_log (firm_id, kind, query, outcome, results, engine) "
                "VALUES (%s, 'sweep', 'q', 'found', '[]'::jsonb, 'serper')",
                (firm_id,),
            )
    refusal = daily_cap_refusal(db, {"daily_cap": "2"}, _serper())
    assert refusal and "daily cap of 2" in refusal
    assert daily_cap_refusal(db, {"daily_cap": "3"}, _serper()) is None
    assert daily_cap_refusal(db, {"daily_cap": "0"}, _serper()) is None  # 0 = no cap
    # The config default is far above two rows.
    assert daily_cap_refusal(db, {}, _serper()) is None
