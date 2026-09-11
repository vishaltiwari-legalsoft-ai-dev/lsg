"""px_site_rules -- the deterministic site-level rules that aren't fee model or
tech fingerprinting: practice area, Spanish intake, an in-house recruiter, and a
government entity_kind. One component, four independent claim types, because all
four read the same stored pages and share one idempotency key per firm.

  * primary_practice + practice_areas (source `rules:practice`) -- practice pages
    weighted by word count, home/about at HALF weight, never the footer (already
    gone -- main_text is boilerplate-stripped by P4). confidence =
    norm_practice's own confidence x 0.8, since a rule ranks below the LLM.
    Evidence is the strongest matching phrase plus ~80 chars of context.
  * spanish_intake (source `rules:site`) -- a Spanish-intake phrase on ANY page,
    or a /es/ URL path, or hreflang="es" in raw HTML. Evidence required; no
    match, no claim (absence of evidence is not false).
  * has_inhouse_recruiter (source `rules:site`) -- an in-house recruiting title
    named on a team/careers/about page. Evidence required.
  * entity_kind = 'gov' (source `rules:site`, 0.95) -- firm.domain ends in
    .gov/.mil or a state-government "state.XX.us" suffix.

Patterns live in config/site_rules.yml (Spanish phrases, recruiter titles, gov
domain suffixes) and config/practice_areas.yml (shared with lge.norm.practice,
read again here only to locate the evidence span norm_practice's own aggregate
score doesn't expose).
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from lge.norm import norm_practice
from lge.planes.p._claims import (
    compute_input_hash,
    config_fingerprint,
    fetch_documents_with_text,
    read_html,
    select_firm_ids,
    write_claim,
)
from lge.registry import RunContext, RunResult, component
from lge.store.objects import ObjectStore, get_store

_VERSION = "px:v1"
_SOURCE_PRACTICE = "rules:practice"
_SOURCE_SITE = "rules:site"

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
# Mirrors lge/norm/practice.py's own _CONFIG_PATH -- computed independently
# rather than importing that module's private constant (see p6_fee.py).
_PRACTICE_CONFIG_PATH = _PROJECT_ROOT / "config" / "practice_areas.yml"
_SITE_RULES_CONFIG_PATH = _PROJECT_ROOT / "config" / "site_rules.yml"

_PRACTICE_PAGE_KINDS = ("practice", "home", "about")
_RECRUITER_PAGE_KINDS = ("team", "careers", "about")
_EVIDENCE_CONTEXT = 40  # chars each side of a match -> ~80 chars total

_SITE_CONFIDENCE = 0.9
_GOV_CONFIDENCE = 0.95

_HREFLANG_ES_RE = re.compile(
    r'<link[^>]+hreflang\s*=\s*["\']es(?:-[A-Za-z]{2})?["\'][^>]*>', re.IGNORECASE
)
_ES_URL_PATH_RE = re.compile(r"(?:^|/)es(?:/|$)", re.IGNORECASE)


@functools.lru_cache(maxsize=1)
def _practice_patterns() -> dict[str, tuple[re.Pattern[str], ...]]:
    with _PRACTICE_CONFIG_PATH.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    return {
        slug: tuple(re.compile(p, re.IGNORECASE) for p in patterns)
        for slug, patterns in cfg["practices"].items()
    }


@functools.lru_cache(maxsize=1)
def _site_rules_config() -> dict:
    with _SITE_RULES_CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@functools.lru_cache(maxsize=1)
def _spanish_patterns() -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in _site_rules_config()["spanish_phrases"])


@functools.lru_cache(maxsize=1)
def _recruiter_patterns() -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in _site_rules_config()["recruiter_roles"])


@functools.lru_cache(maxsize=1)
def _gov_patterns() -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in _site_rules_config()["gov_domain_patterns"])


def _context(text: str, start: int, end: int) -> str:
    lo = max(0, start - _EVIDENCE_CONTEXT)
    hi = min(len(text), end + _EVIDENCE_CONTEXT)
    return text[lo:hi].strip()


@component(
    "px_site_rules",
    "P",
    "Site rules: primary_practice/practice_areas, spanish_intake, has_inhouse_recruiter, gov",
)
def run(ctx: RunContext, *, store: ObjectStore | None = None, **opts: object) -> RunResult:
    store = store or get_store()
    result = RunResult()
    firm_ids = select_firm_ids(
        ctx.conn,
        firm_ids_file=opts.get("firm_ids_file"),  # type: ignore[arg-type]
        limit=opts.get("limit"),  # type: ignore[arg-type]
    )
    version = f"{_VERSION}:{config_fingerprint(_PRACTICE_CONFIG_PATH, _SITE_RULES_CONFIG_PATH)}"

    for firm_id in firm_ids:
        try:
            rows = fetch_documents_with_text(ctx.conn, firm_id)
            if not rows:
                result.skipped += 1
                continue

            domain = _firm_domain(ctx.conn, firm_id)
            input_hash = compute_input_hash(
                [*(r["content_hash"] for r in rows), domain or ""], version
            )
            with ctx.once("px_site_rules", str(firm_id), input_hash) as should_run:
                if not should_run:
                    result.skipped += 1
                    continue
                _claim_practice(ctx.conn, firm_id, rows)
                _claim_spanish_intake(ctx.conn, firm_id, rows, store)
                _claim_recruiter(ctx.conn, firm_id, rows)
                _claim_gov(ctx.conn, firm_id, domain, rows)
            result.processed += 1
        except Exception as exc:  # noqa: BLE001 -- per-firm isolation, never global
            result.failed += 1
            result.notes.append(f"px_site_rules firm={firm_id}: {exc}")

    return result


def _firm_domain(conn: Any, firm_id: Any) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT domain FROM firm WHERE id = %s", (firm_id,))
        row = cur.fetchone()
    return row["domain"] if row else None


def _claim_practice(conn: Any, firm_id: Any, rows: list[dict]) -> None:
    practice_rows = [r for r in rows if r["page_kind"] in _PRACTICE_PAGE_KINDS]
    if not practice_rows:
        return

    sections: list[tuple[str, float]] = []
    for r in practice_rows:
        text = r["main_text"] or ""
        word_count = r["word_count"] if r["word_count"] else len(text.split())
        weight = float(word_count) * (1.0 if r["page_kind"] == "practice" else 0.5)
        sections.append((text, weight))

    practice_result = norm_practice(sections)
    if practice_result.primary is None:
        return

    # Evidence search order follows the weighting rationale: real estate on the
    # practice pages themselves first, home/about (half weight) second.
    ordered_texts = [r["main_text"] or "" for r in practice_rows if r["page_kind"] == "practice"]
    ordered_texts += [r["main_text"] or "" for r in practice_rows if r["page_kind"] != "practice"]
    evidence = _strongest_evidence(practice_result.primary, ordered_texts)

    confidence = practice_result.confidence * 0.8
    newest = max(r["fetched_at"] for r in practice_rows)

    write_claim(
        conn, firm_id, "primary_practice", practice_result.primary,
        _SOURCE_PRACTICE, confidence, evidence, newest,
    )
    areas = [slug for slug, _share in practice_result.areas]
    write_claim(
        conn, firm_id, "practice_areas", areas, _SOURCE_PRACTICE, confidence, evidence, newest
    )


def _strongest_evidence(slug: str, texts: list[str]) -> str | None:
    for text in texts:
        if not text:
            continue
        for pattern in _practice_patterns().get(slug, ()):
            m = pattern.search(text)
            if m:
                return _context(text, m.start(), m.end())
    return None


def _claim_spanish_intake(conn: Any, firm_id: Any, rows: list[dict], store: ObjectStore) -> None:
    for r in rows:  # already ordered fetched_at ASC, id ASC
        text = r["main_text"]
        if text:
            for pattern in _spanish_patterns():
                m = pattern.search(text)
                if m:
                    evidence = _context(text, m.start(), m.end())
                    write_claim(
                        conn, firm_id, "spanish_intake", True, _SOURCE_SITE,
                        _SITE_CONFIDENCE, evidence, r["fetched_at"],
                    )
                    return

        url = r["url"] or ""
        if url and _ES_URL_PATH_RE.search(urlsplit(url).path):
            write_claim(
                conn, firm_id, "spanish_intake", True, _SOURCE_SITE,
                _SITE_CONFIDENCE, f"url path indicates a Spanish alternate: {url}", r["fetched_at"],
            )
            return

        html = read_html(store, r["object_key"])
        if html:
            m = _HREFLANG_ES_RE.search(html)
            if m:
                write_claim(
                    conn, firm_id, "spanish_intake", True, _SOURCE_SITE,
                    _SITE_CONFIDENCE, m.group(0)[:160], r["fetched_at"],
                )
                return


def _claim_recruiter(conn: Any, firm_id: Any, rows: list[dict]) -> None:
    recruiter_rows = [r for r in rows if r["page_kind"] in _RECRUITER_PAGE_KINDS]
    for r in recruiter_rows:
        text = r["main_text"]
        if not text:
            continue
        for pattern in _recruiter_patterns():
            m = pattern.search(text)
            if m:
                evidence = _context(text, m.start(), m.end())
                write_claim(
                    conn, firm_id, "has_inhouse_recruiter", True, _SOURCE_SITE,
                    _SITE_CONFIDENCE, evidence, r["fetched_at"],
                )
                return


def _claim_gov(conn: Any, firm_id: Any, domain: str | None, rows: list[dict]) -> None:
    if not domain:
        return
    d = domain.strip().lower()
    suffixes = tuple(_site_rules_config()["gov_domain_suffixes"])
    is_gov = d.endswith(suffixes) or any(p.search(d) for p in _gov_patterns())
    if not is_gov:
        return
    newest = max(r["fetched_at"] for r in rows)
    write_claim(conn, firm_id, "entity_kind", "gov", _SOURCE_SITE, _GOV_CONFIDENCE, domain, newest)
