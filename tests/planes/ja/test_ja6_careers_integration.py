"""The real JA1 -> JA6 shape: a careers posting carries firm_id and NO company_name.

Found in the live probe: all 8 postings from firms' own careers pages were rejected as
blind_posting, so zero signals were created. Unit tests missed it because the helper
defaulted company_name to a value the real careers watcher never sets.
"""

import pytest

from tests.conftest import make_firm
from tests.planes.ja._ja6_helpers import fetch_all, fetch_one, make_posting, run_normalise

pytestmark = pytest.mark.db


def test_own_careers_posting_without_company_name_becomes_a_signal(db):
    firm_id = make_firm(db, city="Atlanta", state="GA")
    make_posting(db, source="careers", firm_id=firm_id, company_name=None, title="Case Manager",
                 city="Atlanta", state="GA")
    run_normalise(db)
    rejected = fetch_all(db, "SELECT rule FROM job_posting_rejected")
    assert rejected == []
    signal = fetch_one(
        db, "SELECT kind FROM signal WHERE firm_id = %s AND kind = 'job_posting_open'", (firm_id,)
    )
    assert signal is not None


def test_own_careers_attorney_posting_is_still_not_a_support_role(db):
    firm_id = make_firm(db, city="Atlanta", state="GA")
    make_posting(db, source="careers", firm_id=firm_id, company_name=None,
                 title="Associate Attorney", city="Atlanta", state="GA")
    run_normalise(db)
    assert fetch_all(db, "SELECT rule FROM job_posting_rejected") == [{"rule": "not_support_role"}]


def test_a_board_posting_with_no_company_is_still_blind(db):
    make_posting(db, source="bar_board:example.org", firm_id=None, company_name=None,
                 title="Paralegal", city="Atlanta", state="GA")
    run_normalise(db)
    assert fetch_all(db, "SELECT rule FROM job_posting_rejected") == [{"rule": "blind_posting"}]
