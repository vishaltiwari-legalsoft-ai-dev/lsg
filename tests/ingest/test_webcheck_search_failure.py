"""website_check and a search engine that does not answer: no row is written
(so the firm is asked about again next run instead of waiting out the
recheck window), five failures in a row stop the searching, and a run over
the whole store is refused (security review, 28 Sep 2026)."""

from __future__ import annotations

import pytest

from lge.ingest import webcheck
from lge.search.base import failure
from tests.conftest import make_firm
from tests.ingest.test_webcheck import UA, Recorder, _checks
from tests.planes.p._p_helpers import ctx, make_lead

pytestmark = pytest.mark.db


def test_a_failed_search_writes_no_check_row(db):
    firm_id = make_firm(db, domain=None, canonical_name="Nowhere Legal Group", city="Boise",
                        state="ID")
    make_lead(db, firm_id)
    search = Recorder(failure("search failed: refused -- serper: no credit left"))

    result = webcheck.website_check(ctx(db, live=True, user_agent=UA), search=search,
                                    default_interval_s="0")

    assert result.failed == 1 and result.processed == 0
    assert _checks(db, firm_id) == []  # nothing recorded: asked again next run
    assert any("search failed" in n for n in result.notes)
    assert len(search.queries) == 1


def test_five_failures_in_a_row_stop_the_searching(db):
    ids = []
    for i in range(7):
        fid = make_firm(db, domain=None, canonical_name=f"Firm Number {i} Law", city="Boise",
                        state="ID")
        make_lead(db, fid)
        ids.append(fid)
    search = Recorder(failure("search failed: blocked"))

    result = webcheck.website_check(ctx(db, live=True, user_agent=UA), search=search,
                                    default_interval_s="0")

    assert len(search.queries) == 5  # the sixth and seventh were not asked
    assert result.failed == 7
    assert all(_checks(db, fid) == [] for fid in ids)
    assert any("stopped searching" in n for n in result.notes)


def test_the_whole_store_is_refused_without_a_limit(db, monkeypatch):
    monkeypatch.setattr(webcheck, "paid_run_refusal",
                        lambda opts, what, firms: f"refused: {what} over {firms} firms")
    firm_id = make_firm(db, domain=None, canonical_name="Nowhere Legal Group")
    make_lead(db, firm_id)
    search = Recorder([])

    result = webcheck.website_check(ctx(db, live=True, user_agent=UA), search=search,
                                    default_interval_s="0")

    assert search.queries == [] and _checks(db, firm_id) == []
    assert result.notes and result.notes[0].startswith("refused")
