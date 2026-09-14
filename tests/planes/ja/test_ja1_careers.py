"""JA1 careers page watcher: JSON-LD/microdata/ATS-embed/HTML-heuristic
parse cascade, careers_sweep recorded on every attempt (including failure
and unchanged-hash skip), ATS slugs captured without fetching them, and
Indeed/LinkedIn/ZipRecruiter links recorded but never followed."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from lge.planes.ja import ja1_careers
from lge.registry import RunContext
from lge.settings import Settings, get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "html"
UA = "TestBot/1.0 (+https://example.com/bot)"


def ctx(conn, **overrides) -> RunContext:
    base = get_settings()
    if overrides:
        base = Settings(
            dsn=overrides.get("dsn", base.dsn),
            admin_dsn=overrides.get("admin_dsn", base.admin_dsn),
            object_store=overrides.get("object_store", base.object_store),
            user_agent=overrides.get("user_agent", base.user_agent),
            anthropic_api_key=overrides.get("anthropic_api_key", base.anthropic_api_key),
            openrouter_api_key=overrides.get("openrouter_api_key", base.openrouter_api_key),
            live=overrides.get("live", base.live),
        )
    return RunContext(conn, base)


def make_lead(conn, firm_id, **cols) -> str:
    from lge import db as lge_db

    cols.setdefault("id", str(uuid.uuid4()))
    cols["firm_id"] = firm_id
    cols.setdefault("state", "DISCOVERED")
    cols.setdefault("created_at", datetime.now(UTC))
    columns = list(cols.keys())
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    values = [cols[c] for c in columns]
    with lge_db.lifecycle(conn, "test_setup"), conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO lead ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


def insert_site_map_careers(conn, firm_id, url, via="sitemap"):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO site_map (firm_id, url, page_kind, discovered_via) "
            "VALUES (%s, %s, 'careers', %s)",
            (firm_id, url, via),
        )


def sweeps(conn, firm_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM careers_sweep WHERE firm_id = %s ORDER BY id", (firm_id,)
        )
        return cur.fetchall()


def postings(conn, firm_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM raw_posting WHERE firm_id = %s ORDER BY id", (firm_id,)
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Pure parsing functions -- no DB, no network
# ---------------------------------------------------------------------------


def test_jsonld_extraction_from_a_realistic_fixture():
    html = (_FIXTURES / "careers_jsonld.html").read_text(encoding="utf-8")
    parsed = ja1_careers.parse_careers_page(html, "https://example.com/careers")
    assert parsed.method == "jsonld"
    assert len(parsed.postings) == 2

    titles = {p["title"] for p in parsed.postings}
    assert titles == {"Litigation Paralegal", "Legal Assistant"}

    paralegal = next(p for p in parsed.postings if p["title"] == "Litigation Paralegal")
    assert paralegal["board_posted_date"].isoformat() == "2026-09-01"
    assert paralegal["employment_type"] == "FULL_TIME"
    assert paralegal["location_raw"] == "Austin, TX"
    assert paralegal["apply_email"] == "careers@examplelaw.com"
    assert "Litigation Paralegal" in paralegal["body"]
    assert "<p>" not in paralegal["body"]  # HTML stripped from the description


def test_indeed_link_recorded_but_never_a_separate_fetch_target():
    html = (_FIXTURES / "careers_jsonld.html").read_text(encoding="utf-8")
    parsed = ja1_careers.parse_careers_page(html, "https://example.com/careers")
    for p in parsed.postings:
        assert "https://www.indeed.com/viewjob?jk=abc123" in p["outbound_links"]


def test_ats_iframe_captured_as_a_marker_not_a_real_posting():
    html = (_FIXTURES / "careers_ats_iframe.html").read_text(encoding="utf-8")
    parsed = ja1_careers.parse_careers_page(html, "https://example.com/careers")
    assert parsed.method == "ats_embed"
    assert len(parsed.postings) == 1
    p = parsed.postings[0]
    assert p["ats_slug"] == "smithassociates"
    assert p["payload"]["ats_platform"] == "greenhouse"
    assert p["payload"]["embed_url"] == "https://boards.greenhouse.io/smithassociates"


def test_html_heuristic_fixture_extracts_support_roles_only():
    html = (_FIXTURES / "careers_html_heuristic.html").read_text(encoding="utf-8")
    parsed = ja1_careers.parse_careers_page(html, "https://example.com/careers")
    assert parsed.method == "html"
    titles = {p["title"] for p in parsed.postings}
    assert titles == {
        "Legal Assistant - Apply now to join our growing team",
        "Paralegal (Full-time) - View this position",
    }
    assert not any("Holiday Party" in t for t in titles)
    assert all(p["payload"]["parse_method"] == "html" for p in parsed.postings)
    assert all(p["payload"]["confidence"] < 0.5 for p in parsed.postings)


def test_single_posting_page_is_one_posting():
    # butlerfirm.com's shape (D-026): the page is the posting, not a list of them.
    html = (
        "<html><head><title>B|K is Hiring a Personal Injury Paralegal - Butler Kahn</title>"
        "<script>async function cache(e,t){try{if(-1!=e.indexOf('x'))return}catch(r){}}"
        "</script></head><body><nav>Home About Contact</nav>"
        "<h1>We are Hiring a Paralegal</h1>"
        "<p>Butler Kahn is looking for an experienced paralegal to join our Atlanta "
        "office. Send your resume to jobs@butlerfirm.com.</p></body></html>"
    )
    parsed = ja1_careers.parse_careers_page(
        html, "https://butlerfirm.com/hiring-personal-injury-paralegal-atlanta-ga/"
    )
    assert parsed.method == "html"
    assert [p["payload"]["role"] for p in parsed.postings] == ["paralegal"]
    posting = parsed.postings[0]
    assert posting["title"] == "Paralegal"
    assert posting["apply_email"] == "jobs@butlerfirm.com"
    # the body is the firm's own words from the announcement on: no script, no nav
    assert posting["body"].startswith("We are Hiring a Paralegal Butler Kahn is looking")
    assert "function" not in posting["body"]


@pytest.mark.parametrize(
    "h1",
    [
        "Is Hiring a Lawyer Worth It?",
        "We are hiring",
        "Hiring a Car Accident Lawyer: What to Expect",
        "Now Hiring an Associate Attorney",
    ],
)
def test_hiring_phrases_that_are_not_support_postings(h1):
    html = f"<html><body><h1>{h1}</h1><p>Some article text about the topic.</p></body></html>"
    assert ja1_careers.parse_careers_page(html, "https://firm.com/blog/x").method == "none"


def test_is_excluded_board_host():
    assert ja1_careers.is_excluded_board_host("indeed.com") is True
    assert ja1_careers.is_excluded_board_host("www.indeed.com") is True
    assert ja1_careers.is_excluded_board_host("indeed.com.evil.example") is False
    assert ja1_careers.is_excluded_board_host("linkedin.com") is True
    assert ja1_careers.is_excluded_board_host("ziprecruiter.com") is True
    assert ja1_careers.is_excluded_board_host("example.com") is False


def test_empty_page_parses_to_none():
    parsed = ja1_careers.parse_careers_page("   ", "https://example.com/careers")
    assert parsed.method == "none"
    assert parsed.postings == []


# ---------------------------------------------------------------------------
# Full component flow
# ---------------------------------------------------------------------------


@respx.mock
def test_jsonld_sweep_writes_raw_posting_rows_with_firm_id_set(db):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    respx.get("https://example.com/careers").mock(
        return_value=httpx.Response(
            200, content=(_FIXTURES / "careers_jsonld.html").read_bytes()
        )
    )

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map_careers(db, firm_id, "https://example.com/careers")

    result = ja1_careers.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")
    assert result.processed == 1

    rows = postings(db, firm_id)
    assert len(rows) == 2
    assert all(str(r["firm_id"]) == str(firm_id) for r in rows)
    assert all(r["source"] == "careers" for r in rows)
    assert all(r["fetch_ok"] for r in rows)

    sw = sweeps(db, firm_id)
    assert len(sw) == 1
    assert sw[0]["fetch_ok"] is True
    assert sw[0]["postings_found"] == 2
    assert sw[0]["parse_method"] == "jsonld"


@respx.mock
def test_ats_iframe_slug_captured_without_fetching_the_ats(db):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    respx.get("https://example.com/careers").mock(
        return_value=httpx.Response(
            200, content=(_FIXTURES / "careers_ats_iframe.html").read_bytes()
        )
    )
    # Deliberately NOT mocked -- if the code ever fetched it, respx would
    # raise for an unmatched request and this test would fail loudly.
    greenhouse_route = respx.get("https://boards.greenhouse.io/smithassociates")

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map_careers(db, firm_id, "https://example.com/careers")

    ja1_careers.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")

    assert greenhouse_route.call_count == 0
    rows = postings(db, firm_id)
    assert len(rows) == 1
    assert rows[0]["ats_slug"] == "smithassociates"
    assert rows[0]["payload"]["ats_platform"] == "greenhouse"


@respx.mock
def test_link_to_indeed_is_recorded_not_followed(db):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    respx.get("https://example.com/careers").mock(
        return_value=httpx.Response(
            200, content=(_FIXTURES / "careers_jsonld.html").read_bytes()
        )
    )
    indeed_route = respx.get("https://www.indeed.com/viewjob", params={"jk": "abc123"})

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map_careers(db, firm_id, "https://example.com/careers")

    ja1_careers.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")

    assert indeed_route.call_count == 0
    rows = postings(db, firm_id)
    assert any(
        "https://www.indeed.com/viewjob?jk=abc123" in (r["outbound_links"] or []) for r in rows
    )


@respx.mock
def test_sweep_recorded_on_fetch_failure(db):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    respx.get("https://example.com/careers").mock(side_effect=httpx.ConnectError("refused"))

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map_careers(db, firm_id, "https://example.com/careers")

    result = ja1_careers.run(
        ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0"
    )
    assert result.processed == 1

    sw = sweeps(db, firm_id)
    assert len(sw) == 1
    assert sw[0]["fetch_ok"] is False
    assert sw[0]["postings_found"] is None
    assert sw[0]["content_hash"] is None
    assert sw[0]["parse_method"] is None
    assert postings(db, firm_id) == []


@respx.mock
def test_unchanged_hash_skips_parsing_and_carries_over_count(db):
    body = (_FIXTURES / "careers_jsonld.html").read_bytes()
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    respx.get("https://example.com/careers").mock(return_value=httpx.Response(200, content=body))

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map_careers(db, firm_id, "https://example.com/careers")

    # First sweep -- parses normally.
    ja1_careers.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")
    first_sweeps = sweeps(db, firm_id)
    assert len(first_sweeps) == 1
    assert first_sweeps[0]["parse_method"] == "jsonld"
    assert first_sweeps[0]["postings_found"] == 2
    n_postings_after_first = len(postings(db, firm_id))

    # Force a second sweep attempt today by clearing this firm's task_run
    # marker (the real trigger is "tomorrow"; this isolates the hash-skip
    # behaviour from the once-per-day guard).
    with db.cursor() as cur:
        cur.execute("DELETE FROM task_run WHERE component = 'ja1_careers'")

    ja1_careers.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")

    all_sweeps = sweeps(db, firm_id)
    assert len(all_sweeps) == 2
    assert all_sweeps[1]["parse_method"] == "none"  # skipped -- hash unchanged
    assert all_sweeps[1]["postings_found"] == 2  # carried over from the previous sweep
    assert all_sweeps[1]["content_hash"] == first_sweeps[0]["content_hash"]
    # No re-parsing means no new raw_posting rows were written.
    assert len(postings(db, firm_id)) == n_postings_after_first


@respx.mock
def test_probe_cascade_stops_at_first_non_404(db):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    respx.get("https://example.com/careers").mock(return_value=httpx.Response(404))
    respx.get("https://example.com/jobs").mock(
        return_value=httpx.Response(200, content=(_FIXTURES / "careers_jsonld.html").read_bytes())
    )
    employment_route = respx.get("https://example.com/employment")

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    # No site_map careers row -- forces the probe cascade.

    ja1_careers.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")

    assert employment_route.call_count == 0  # never tried past the first hit
    sw = sweeps(db, firm_id)
    assert len(sw) == 1
    assert sw[0]["url"] == "https://example.com/jobs"
    assert sw[0]["postings_found"] == 2


@pytest.mark.parametrize(
    "url,final_url,expected",
    [
        # real redirects from the probe (D-026): 14 of 31 "careers pages" were these
        ("https://shiverhamilton.com/careers", "https://www.shiverhamilton.com", True),
        ("https://newlandlaw.com/careers", "https://www.newlandlaw.com/404", True),
        ("https://vlhlaw.com/careers", "https://www.vlhlaw.com/404?aspxerrorpath=/page.aspx", True),
        ("https://hgroveslaw.com/careers", "https://hgroveslaw.com/index.php?error=404", True),
        ("https://dresslerlawllp.com/careers", "https://sdonylaw.com/", True),
        # ordinary redirects keep the page
        ("https://firm.com/careers", "https://www.firm.com/careers/", False),
        ("https://firm.com/careers", "https://firm.com/careers/openings", False),
        ("https://firm.com/careers", None, False),
    ],
)
def test_redirected_away(url, final_url, expected):
    assert ja1_careers.redirected_away(url, final_url) is expected


@respx.mock
def test_probe_redirected_to_homepage_is_not_a_careers_page(db):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    respx.get("https://example.com/careers").mock(
        return_value=httpx.Response(301, headers={"location": "https://www.example.com/"})
    )
    respx.get("https://www.example.com/").mock(
        return_value=httpx.Response(200, html="<html><body><h1>Welcome</h1></body></html>")
    )
    respx.get("https://example.com/jobs").mock(
        return_value=httpx.Response(200, content=(_FIXTURES / "careers_jsonld.html").read_bytes())
    )

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)

    ja1_careers.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")

    sw = sweeps(db, firm_id)
    assert len(sw) == 1
    assert sw[0]["url"] == "https://example.com/jobs"  # the cascade kept going
    assert sw[0]["postings_found"] == 2


@respx.mock
def test_found_careers_url_beats_the_guessed_probe(db):
    # The probe's real shape (butlerfirm.com): the map holds the guessed /careers
    # and a posting URL the sitemap published. Alphabetical order used to pick the
    # guess, 404, and stop (D-026).
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    guess = respx.get("https://example.com/careers").mock(return_value=httpx.Response(404))
    respx.get("https://example.com/hiring-personal-injury-paralegal/").mock(
        return_value=httpx.Response(200, content=(_FIXTURES / "careers_jsonld.html").read_bytes())
    )
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map_careers(db, firm_id, "https://example.com/careers", via="probe")
    insert_site_map_careers(
        db, firm_id, "https://example.com/hiring-personal-injury-paralegal/", via="sitemap"
    )

    ja1_careers.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")

    assert guess.call_count == 0
    sw = sweeps(db, firm_id)
    assert [s["url"] for s in sw] == ["https://example.com/hiring-personal-injury-paralegal/"]
    assert sw[0]["postings_found"] == 2


@respx.mock
def test_map_with_only_guesses_uses_the_full_cascade(db):
    # Probe rows in the map are the cascade's own guesses; a 404 on the first must
    # not end the search.
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    respx.get("https://example.com/careers").mock(return_value=httpx.Response(404))
    respx.get("https://example.com/jobs").mock(
        return_value=httpx.Response(200, content=(_FIXTURES / "careers_jsonld.html").read_bytes())
    )
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map_careers(db, firm_id, "https://example.com/careers", via="probe")

    ja1_careers.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")

    sw = sweeps(db, firm_id)
    assert [s["url"] for s in sw] == ["https://example.com/jobs"]
    assert sw[0]["postings_found"] == 2


@respx.mock
def test_every_found_careers_url_is_swept(db):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    respx.get("https://example.com/careers/").mock(
        return_value=httpx.Response(200, html="<html><body><p>We love our team.</p></body></html>")
    )
    respx.get("https://example.com/careers/paralegal/").mock(
        return_value=httpx.Response(200, content=(_FIXTURES / "careers_jsonld.html").read_bytes())
    )
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map_careers(db, firm_id, "https://example.com/careers/", via="sitemap")
    insert_site_map_careers(db, firm_id, "https://example.com/careers/paralegal/", via="link")

    result = ja1_careers.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")

    assert result.processed == 1
    sw = sweeps(db, firm_id)
    assert len(sw) == 2
    assert sum(s["postings_found"] for s in sw) == 2


@respx.mock
def test_site_map_careers_url_redirected_home_is_recorded_not_parsed(db):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    respx.get("https://example.com/careers").mock(
        return_value=httpx.Response(301, headers={"location": "https://example.com/"})
    )
    respx.get("https://example.com/").mock(
        return_value=httpx.Response(200, html="<html><body><h2>Paralegal</h2></body></html>")
    )
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map_careers(db, firm_id, "https://example.com/careers")

    ja1_careers.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")

    sw = sweeps(db, firm_id)
    assert len(sw) == 1
    assert sw[0]["postings_found"] == 0
    assert sw[0]["parse_method"] == "redirected"
    assert postings(db, firm_id) == []


@respx.mock
def test_all_probes_404_records_definitive_absence(db):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    for path in ("/careers", "/jobs", "/employment-opportunities", "/join-our-team"):
        respx.get(f"https://example.com{path}").mock(return_value=httpx.Response(404))

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)

    ja1_careers.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")

    sw = sweeps(db, firm_id)
    assert len(sw) == 1
    assert sw[0]["url"] == "https://example.com/join-our-team"  # the last candidate tried
    assert sw[0]["fetch_ok"] is True
    assert sw[0]["postings_found"] == 0
    assert sw[0]["parse_method"] == "none"


@respx.mock
def test_edge_blocked_host_still_records_one_failed_sweep(db):
    respx.get("https://blocked.example.com/robots.txt").mock(return_value=httpx.Response(403))

    firm_id = make_firm(db, domain="blocked.example.com")
    make_lead(db, firm_id)
    insert_site_map_careers(db, firm_id, "https://blocked.example.com/careers")

    result = ja1_careers.run(
        ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0"
    )
    assert result.processed == 1
    sw = sweeps(db, firm_id)
    assert len(sw) == 1
    assert sw[0]["fetch_ok"] is False


# ---------------------------------------------------------------------------
# Live gate / honest UA / idempotency
# ---------------------------------------------------------------------------


@respx.mock
def test_live_gate_off_makes_no_requests(db):
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map_careers(db, firm_id, "https://example.com/careers")

    result = ja1_careers.run(ctx(db, live=False), limit=10)
    assert "live=0" in " ".join(result.notes)
    assert sweeps(db, firm_id) == []


@respx.mock
def test_empty_user_agent_refuses(db):
    from lge.fetch.client import EmptyUserAgentError

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map_careers(db, firm_id, "https://example.com/careers")

    with pytest.raises(EmptyUserAgentError):
        ja1_careers.run(ctx(db, live=True, user_agent=""), limit=10)


@respx.mock
def test_rerun_same_day_is_a_no_op(db):
    route = respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    respx.get("https://example.com/careers").mock(
        return_value=httpx.Response(
            200, content=(_FIXTURES / "careers_jsonld.html").read_bytes()
        )
    )

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map_careers(db, firm_id, "https://example.com/careers")

    r1 = ja1_careers.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")
    assert r1.processed == 1
    assert route.call_count == 1

    r2 = ja1_careers.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")
    assert r2.processed == 0
    assert r2.skipped == 1
    assert route.call_count == 1  # no second network call today
