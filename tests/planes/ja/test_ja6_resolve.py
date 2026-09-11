"""JA6 stage 3 -- the resolution ladder. Rungs 1-4 and the resolve() unit tested
directly against an in-memory Posting (no raw_posting row needed -- resolve()
only reads `firm`/`ats_slug_map`); rungs 6/7 and the discovery_lead / rejected
paths tested end-to-end through ja6_normalise since that's where
posting_resolution/discovery_lead/job_posting_rejected actually get written.
"""

from __future__ import annotations

import pytest

from lge.norm import norm_addr, norm_name
from lge.planes.ja.ja6_resolve import resolve
from tests.conftest import make_firm
from tests.planes.ja._ja6_helpers import (
    has_discovery_lead,
    make_ats_slug_map,
    make_posting,
    posting,
    rejected_rule,
    resolution_row,
    run_normalise,
)

pytestmark = pytest.mark.db


# =============================================================================
# rung 0 -- already resolved at fetch (careers page)
# =============================================================================


def test_rung0_skips_resolution_when_firm_id_already_set(db):
    firm_id = make_firm(db)
    p = posting(1, firm_id=firm_id, company_name="Irrelevant Name")
    res = resolve(db, p)
    assert (res.firm_id, res.rung) == (str(firm_id), 0)


# =============================================================================
# rung 1 -- apply-email domain, decisive
# =============================================================================


def test_rung1_apply_email_domain(db):
    firm_id = make_firm(db, domain="smithlaw.com")
    p = posting(1, apply_email="careers@smithlaw.com", company_name="Nothing Alike LLC")
    res = resolve(db, p)
    assert (res.firm_id, res.rung) == (str(firm_id), 1)


def test_rung1_ignores_freemail(db):
    # norm_email_domain() blocklists free-mail providers -- a gmail apply
    # address carries no firm identity, so rung 1 never even queries `firm`.
    p = posting(1, apply_email="hr@gmail.com", city=None)
    res = resolve(db, p)
    assert res.rung != 1


# =============================================================================
# rung 2 -- outbound link domain, board/ATS hosts excluded, decisive
# =============================================================================


def test_rung2_outbound_link_excludes_board_hosts(db):
    firm_id = make_firm(db, domain="smithlaw.com")
    p = posting(
        1,
        outbound_links=["https://www.indeed.com/job/123", "https://www.smithlaw.com/careers/1"],
    )
    res = resolve(db, p)
    assert (res.firm_id, res.rung) == (str(firm_id), 2)


def test_rung2_only_board_links_does_not_resolve(db):
    make_firm(db, domain="smithlaw.com")
    p = posting(
        1, outbound_links=["https://www.indeed.com/job/123", "https://www.linkedin.com/x"]
    )
    res = resolve(db, p)
    assert res.firm_id is None


# =============================================================================
# rung 3 -- phone, decisive
# =============================================================================


def test_rung3_phone_match(db):
    firm_id = make_firm(db, phone_e164="+13035551234")
    p = posting(1, phone_raw="(303) 555-1234")
    res = resolve(db, p)
    assert (res.firm_id, res.rung) == (str(firm_id), 3)


# =============================================================================
# rung 4 -- ATS slug map, decisive
# =============================================================================


def test_rung4_ats_slug_map(db):
    firm_id = make_firm(db)
    make_ats_slug_map(db, "greenhouse", "smithlaw", firm_id)
    p = posting(1, source="ats:greenhouse", ats_slug="smithlaw", company_name="Whatever Inc")
    res = resolve(db, p)
    assert (res.firm_id, res.rung) == (str(firm_id), 4)


def test_rung4_unknown_slug_falls_through(db):
    firm_id = make_firm(db)
    make_ats_slug_map(db, "greenhouse", "smithlaw", firm_id)
    p = posting(1, source="ats:greenhouse", ats_slug="someone-else", city=None)
    res = resolve(db, p)
    assert res.firm_id is None
    assert firm_id  # not used for the match -- keeps the row from being pointless


# =============================================================================
# rung 5 -- company name + street address (R3: both addr_hash AND similarity)
# =============================================================================


def test_rung5_address_plus_name_similarity(db):
    addr = norm_addr("123 Main St", "Springfield", "IL", "62704")
    firm_id = make_firm(
        db,
        canonical_name="Smith & Associates",
        name_stem=norm_name("Smith & Associates"),
        addr_hash=addr.addr_hash,
    )
    body = (
        "Smith & Associates is hiring! We are located at 123 Main St, Springfield, "
        "IL 62704. Apply today to join our growing practice."
    )
    p = posting(1, company_name="Smith & Associates", body=body, city=None)
    res = resolve(db, p)
    assert (res.firm_id, res.rung) == (str(firm_id), 5)


def test_rung5_address_alone_without_name_similarity_does_not_resolve(db):
    addr = norm_addr("123 Main St", "Springfield", "IL", "62704")
    make_firm(
        db,
        canonical_name="Totally Different Practice",
        name_stem="totally different practice",
        addr_hash=addr.addr_hash,
    )
    body = "We are located at 123 Main St, Springfield, IL 62704."
    p = posting(1, company_name="Smith & Associates", body=body, city=None)
    res = resolve(db, p)
    assert res.firm_id is None


# =============================================================================
# rung 6 -- company name + city, trigram, exactly one candidate
# =============================================================================


def test_rung6_single_city_candidate_resolves(db):
    firm_id = make_firm(db, name_stem=norm_name("Jones Legal Group"), city="Boulder", state="CO")
    p = posting(1, company_name="Jones Legal Group", city="Boulder", state="CO")
    res = resolve(db, p)
    assert (res.firm_id, res.rung) == (str(firm_id), 6)


def test_rung6_handles_firm_with_city_but_no_state(db):
    # "firms currently often have a city but no state" -- state filters the
    # candidate set only when BOTH sides know one; a firm with state IS NULL is
    # never excluded on that basis.
    firm_id = make_firm(db, name_stem=norm_name("Only City Firm"), city="Reno", state=None)
    p = posting(1, company_name="Only City Firm", city="Reno", state="NV")
    res = resolve(db, p)
    assert (res.firm_id, res.rung) == (str(firm_id), 6)


def test_rung6_two_candidates_is_unresolved_with_discovery_lead(db):
    stem = norm_name("Jones Legal")
    make_firm(db, name_stem=stem, city="Boulder", state="CO")
    make_firm(db, name_stem=stem, city="Boulder", state="CO")
    raw_id = make_posting(
        db,
        source="bar_board:co",
        company_name="Jones Legal",
        city="Boulder",
        state="CO",
        title="Paralegal",
    )

    run_normalise(db)

    assert rejected_rule(db, raw_id) == "unresolved"
    assert has_discovery_lead(db, raw_id)
    assert resolution_row(db, raw_id)["firm_id"] is None
    assert resolution_row(db, raw_id)["rung"] == 6


def test_rung6_zero_candidates_is_unresolved_with_discovery_lead(db):
    raw_id = make_posting(
        db,
        source="bar_board:co",
        company_name="Nobody Has Heard Of This Firm",
        city="Timbuktu",
        state=None,
        title="Paralegal",
    )
    run_normalise(db)
    assert rejected_rule(db, raw_id) == "unresolved"
    assert has_discovery_lead(db, raw_id)


# =============================================================================
# rung 7 -- no usable city
# =============================================================================


@pytest.mark.parametrize("location", ["Remote", "United States", None, ""])
def test_rung7_no_usable_city_is_name_only(db, location):
    raw_id = make_posting(
        db,
        source="bar_board:co",
        company_name="Some Firm LLC",
        city=location or None,
        title="Paralegal",
    )
    run_normalise(db)
    assert rejected_rule(db, raw_id) == "name_only"
    assert not has_discovery_lead(db, raw_id)


# =============================================================================
# purity -- a posting that failed to resolve resolves cleanly once the firm
# exists, and the stale reject/discovery_lead rows are cleared
# =============================================================================


def test_resolution_converges_once_the_firm_enters_the_universe(db):
    raw_id = make_posting(
        db,
        source="bar_board:co",
        company_name="New Firm On The Block",
        city="Golden",
        state="CO",
        title="Paralegal",
    )
    run_normalise(db)
    assert rejected_rule(db, raw_id) == "unresolved"
    assert has_discovery_lead(db, raw_id)

    firm_id = make_firm(
        db, name_stem=norm_name("New Firm On The Block"), city="Golden", state="CO"
    )
    run_normalise(db)

    assert rejected_rule(db, raw_id) is None
    assert not has_discovery_lead(db, raw_id)
    row = resolution_row(db, raw_id)
    assert (row["firm_id"], row["rung"]) == (firm_id, 6)
