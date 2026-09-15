"""r_search_emails -- the addresses a web search finds (Plane R, D-035).

A firm's own site prints one inbox; the people's addresses are printed
elsewhere -- bar directories, Avvo/Justia profiles, court filings, event
programmes, PDFs. Two DuckDuckGo queries read those off the result snippets
(never the pages behind them):

  * for the firm:              "@<domain>"
  * for each decision-maker without an address (owner, admin, attorney;
    at most four per firm):    "<person>" "<firm>" email

An address on the firm's domain is attached to the one named contact it
renders from (jane.doe@ -> Jane Doe, under R3's patterns), or to the person
the snippet names beside it; a general inbox becomes `general_email`, a
hiring inbox `hiring_email`; every address found is kept in `search_emails`
with the result it came from. Off-domain addresses (gmail and the like)
are recorded, never attached: a namesake's inbox is not this person's.
What is attached feeds r3_email_pattern, which learns the firm's scheme
from it and mints addresses for the rest of the named people.

Every query is logged in `search_log` (kinds 'emails' and 'person_email');
a found/not-found answer stands for `recheck_days`, a failure is retried.
Network work: runs only under live=1, throttled like every other search.
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from lge.ingest.webcheck import ddg_search
from lge.planes.p._claims import write_claim
from lge.planes.r.r3_email_pattern import infer_pattern
from lge.planes.r.r_site_emails import (
    _GENERAL_LOCALS,
    _HIRING_LOCALS,
    _pick,
    extract_site_emails,
    local_kind,
    match_contact,
)
from lge.registry import RunContext, RunResult, component

_COMPONENT = "r_search_emails"
_SOURCE = "search:ddg"
_RECHECK_DAYS_DEFAULT = 90
_MAX_PEOPLE_PER_FIRM = 4
_MAX_RESULTS = 8
_MAX_CONSECUTIVE_FAILURES = 5
_ROLE_ORDER = {"owner": 0, "admin": 1, "attorney": 2, "unknown": 3}
_CONFIDENCE = 0.7

SearchFn = Callable[[str, int], list[dict[str, str]]]

_ANY_EMAIL_RE = re.compile(r"[A-Za-z0-9][\w.+-]*@(?:[\w-]+\.)+[A-Za-z]{2,}")
_FILE_LIKE_RE = re.compile(r"\.(?:png|jpe?g|gif|svg|webp|js|css|pdf)$", re.I)


def firm_query(domain: str) -> str:
    return f'"@{domain}"'


def person_query(firm_name: str, person: str) -> str:
    return f'"{person}" "{firm_name}" email'


def _result_text(r: dict[str, str]) -> str:
    return html_lib.unescape(f"{r.get('title') or ''} {r.get('body') or ''} {r.get('href') or ''}")


def emails_in_results(
    results: list[dict[str, str]], domain: str
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """({on-domain email: result}, {off-domain email: result}) -- the first
    result each address appears in."""
    on: dict[str, dict[str, str]] = {}
    off: dict[str, dict[str, str]] = {}
    for r in results:
        text = _result_text(r)
        for email in extract_site_emails(text, domain):
            on.setdefault(email, r)
        for m in _ANY_EMAIL_RE.finditer(text):
            email = m.group(0).lower()
            if email not in on and not _FILE_LIKE_RE.search(email):
                off.setdefault(email, r)
    return on, off


def _names_in(text: str, full_name: str) -> bool:
    tokens = [t for t in re.split(r"[^a-z]+", full_name.casefold()) if len(t) > 1]
    if len(tokens) < 2:
        return False
    low = text.casefold()
    return tokens[0] in low and tokens[-1] in low


def attach_for_person(
    person: dict[str, Any], on_domain: dict[str, dict[str, str]]
) -> tuple[str, str] | None:
    """(email, pattern) for the address in the person's own results that is
    theirs: one that renders from their name, or -- when exactly one personal
    address is printed in a snippet that names them -- that one ('other')."""
    for email in on_domain:
        pattern = infer_pattern(person["full_name"], email)
        if pattern != "other":
            return email, pattern
    named = [
        email for email, r in on_domain.items()
        if local_kind(email) == "person" and _names_in(_result_text(r), person["full_name"])
    ]
    if len(named) == 1:
        return named[0], "other"
    return None


def _failed(results: list[dict]) -> bool:
    return len(results) == 1 and (results[0].get("body") or "").startswith("search failed")


def _log(
    conn: Any, firm_id: Any, kind: str, query: str, outcome: str, results: list[dict], *,
    contact_id: Any = None, url: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO search_log (firm_id, kind, contact_id, query, outcome, url, results) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (firm_id, kind, contact_id, query, outcome, url, Jsonb(results[:_MAX_RESULTS])),
        )


def _searched(conn: Any, kind: str, recheck_days: int, *, firm_id: Any = None,
              contact_id: Any = None) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM search_log WHERE kind = %s AND outcome <> 'failed' "
            "AND searched_at > now() - make_interval(days => %s) "
            "AND (%s::uuid IS NULL OR firm_id = %s) AND (%s::uuid IS NULL OR contact_id = %s) "
            "LIMIT 1",
            (kind, recheck_days, firm_id, firm_id, contact_id, contact_id),
        )
        return cur.fetchone() is not None


def _firm_ids(conn: Any, opts: dict[str, Any], recheck_days: int) -> list[Any]:
    firm_ids_file = opts.get("firm_ids_file")
    if firm_ids_file:
        return [
            line.strip()
            for line in Path(str(firm_ids_file)).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    query = """
        SELECT DISTINCT f.id AS firm_id FROM firm f
        WHERE f.domain IS NOT NULL
          AND (NOT EXISTS (SELECT 1 FROM search_log s WHERE s.firm_id = f.id AND s.kind = 'emails'
                           AND s.outcome <> 'failed'
                           AND s.searched_at > now() - make_interval(days => %s))
               OR EXISTS (SELECT 1 FROM contact c WHERE c.firm_id = f.id
                          AND NOT EXISTS (SELECT 1 FROM contact_email e WHERE e.contact_id = c.id)
                          AND NOT EXISTS (SELECT 1 FROM search_log s WHERE s.contact_id = c.id
                                          AND s.kind = 'person_email' AND s.outcome <> 'failed'
                                          AND s.searched_at > now() - make_interval(days => %s))))
        ORDER BY f.id
    """
    params: list[Any] = [recheck_days, recheck_days]
    limit = opts.get("limit")
    if limit not in (None, ""):
        query += " LIMIT %s"
        params.append(int(limit))
    with conn.cursor() as cur:
        cur.execute(query, params)
        return [r["firm_id"] for r in cur.fetchall()]


def _contacts(conn: Any, firm_id: Any) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.id, c.full_name, c.role, c.confidence, "
            "EXISTS (SELECT 1 FROM contact_email e WHERE e.contact_id = c.id) AS has_email "
            "FROM contact c WHERE c.firm_id = %s ORDER BY c.id",
            (firm_id,),
        )
        return cur.fetchall()


def _attach(conn: Any, contact_id: Any, email: str, pattern: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO contact_email (contact_id, email, status, pattern) "
            "VALUES (%s, %s, 'unverified', %s) ON CONFLICT DO NOTHING",
            (contact_id, email, pattern),
        )
        return cur.rowcount


def _attach_matching(conn: Any, found: dict[str, dict[str, str]], contacts: list[dict]) -> int:
    """Every personal address found so far goes to the one contact without
    an address it renders from -- before anyone is searched for by name, so
    a person the firm query already answered is not asked about again."""
    attached = 0
    for email in sorted(found):
        if local_kind(email) != "person":
            continue
        match = match_contact(email, [c for c in contacts if not c["has_email"]])
        if match:
            contact, pattern = match
            attached += _attach(conn, contact["id"], email, pattern)
            contact["has_email"] = True
    return attached


@component(
    _COMPONENT, "R",
    "Web search: addresses on the firm's domain, and each decision-maker's, from result snippets",
)
def run(ctx: RunContext, *, search: SearchFn | None = None, **opts: Any) -> RunResult:
    conn = ctx.conn
    result = RunResult()
    search = search or ddg_search
    live = bool(ctx.settings.live) or str(opts.get("live", "")) in ("1", "true", "True")
    if not live:
        result.notes.append("live=0: web search is network work -- nothing searched")
        return result
    recheck_days = int(opts.get("recheck_days") or _RECHECK_DAYS_DEFAULT)
    now = datetime.now(UTC)
    attached_total = found_total = 0
    consecutive_failures = 0  # five in a row: the network, not the queries -- stop
    last_failure = ""

    def ask(query: str) -> list[dict[str, str]]:
        nonlocal last_failure
        results = search(query, _MAX_RESULTS)
        if _failed(results):
            last_failure = results[0].get("body") or ""
        return results

    for firm_id in _firm_ids(conn, opts, recheck_days):
        if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            result.notes.append(
                f"stopped early: {consecutive_failures} searches failed in a row "
                f"({last_failure}) -- the rest wait for the next run"
            )
            break
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT canonical_name, domain FROM firm WHERE id = %s", (firm_id,))
                firm = cur.fetchone()
            if firm is None or not firm["domain"]:
                result.skipped += 1
                continue
            domain = firm["domain"].lower()
            contacts = _contacts(conn, firm_id)
            found: dict[str, dict[str, str]] = {}
            off_domain: dict[str, dict[str, str]] = {}
            attached = 0
            did_something = False

            if not _searched(conn, "emails", recheck_days, firm_id=firm_id):
                query = firm_query(domain)
                results = ask(query)
                did_something = True
                if _failed(results):
                    consecutive_failures += 1
                    _log(conn, firm_id, "emails", query, "failed", results)
                else:
                    consecutive_failures = 0
                    on, off = emails_in_results(results, domain)
                    found.update(on)
                    off_domain.update(off)
                    _log(conn, firm_id, "emails", query, "found" if on else "not_found", results,
                         url=next(iter(on.values()))["href"] if on else None)
            attached += _attach_matching(conn, found, contacts)

            people = [c for c in contacts if not c["has_email"]
                      and not _searched(conn, "person_email", recheck_days, contact_id=c["id"])]
            people.sort(key=lambda c: (_ROLE_ORDER.get(c["role"] or "unknown", 3),
                                       -float(c["confidence"] or 0)))
            for person in people[:_MAX_PEOPLE_PER_FIRM]:
                if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    break
                query = person_query(firm["canonical_name"], person["full_name"])
                results = ask(query)
                did_something = True
                if _failed(results):
                    consecutive_failures += 1
                    _log(conn, firm_id, "person_email", query, "failed", results,
                         contact_id=person["id"])
                    continue
                consecutive_failures = 0
                on, off = emails_in_results(results, domain)
                found.update(on)
                off_domain.update(off)
                hit = attach_for_person(person, on)
                if hit:
                    email, pattern = hit
                    attached += _attach(conn, person["id"], email, pattern)
                    person["has_email"] = True
                _log(conn, firm_id, "person_email", query, "found" if hit else "not_found",
                     results, contact_id=person["id"], url=on[hit[0]]["href"] if hit else None)

            # Whatever else came back on the firm's domain: to the person it
            # renders from, or to the firm as its general / hiring inbox.
            attached += _attach_matching(conn, found, contacts)
            general = _pick([e for e in found if local_kind(e) == "general"], _GENERAL_LOCALS)
            hiring = _pick([e for e in found if local_kind(e) == "hiring"], _HIRING_LOCALS)
            if general:
                write_claim(conn, firm_id, "general_email", general, _SOURCE, _CONFIDENCE,
                            found[general]["href"], now)
            if hiring:
                write_claim(conn, firm_id, "hiring_email", hiring, _SOURCE, _CONFIDENCE,
                            found[hiring]["href"], now)
            if found or off_domain:
                entries = [{"email": e, "url": r.get("href"), "on_domain": True}
                           for e, r in sorted(found.items())]
                entries += [{"email": e, "url": r.get("href"), "on_domain": False}
                            for e, r in sorted(off_domain.items())]
                write_claim(conn, firm_id, "search_emails", entries, _SOURCE, _CONFIDENCE,
                            f"{len(found)} on {domain}, {len(off_domain)} elsewhere", now)
            found_total += len(found)
            attached_total += attached
            if did_something:
                result.processed += 1
            else:
                result.skipped += 1
        except Exception as exc:  # noqa: BLE001 -- per-firm isolation, never global
            result.failed += 1
            result.notes.append(f"{_COMPONENT} firm={firm_id}: {exc}")
        ctx.checkpoint()

    result.notes.append(
        f"addresses found on firm domains {found_total}, attached to named people {attached_total}"
    )
    return result
