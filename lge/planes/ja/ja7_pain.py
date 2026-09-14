"""ja7_pain_signals -- intent read from pain (Plane JA, D-033).

Reads three claims and writes signals, the same rows the job-signal
pipeline writes, so the intent score and the proof panel need nothing new:

  * `site_gaps` (px_site_facts)
      no_online_intake AND no_live_chat   -> no_intake_channel
      no_support_staff_listed             -> no_support_staff_listed
      stale_copyright OR stale_news       -> stale_site
    One signal per firm and kind, first seen when the gap was first read.
    A gap the next crawl finds filled closes its signal.
  * `search_review_snippets` (r_search_links)
      a snippet that names the firm and complains about being unreachable
      ("never called me back", "no communication", "took months to")
                                          -> review_unreturned_call
    One signal per snippet, the offending sentence as the quote.
  * `growth_news` (px_site_facts)
      a headline from the last year about a new office, a hire, a
      promotion                           -> new_office_or_lateral
    One signal per post, first seen on the post's date.

Testimonials on the firm's own site are praise by construction (and the
complaint in "the other firm never called me back, then I found X" is about
the other firm), so they are read for what the firm competes on, never for
pain. Idempotent per firm on the claims read; a re-run over unchanged claims
writes nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from lge.planes.ja.ja6_signals import _upsert_signal
from lge.registry import RunContext, RunResult, component

_COMPONENT = "ja7_pain_signals"
_VERSION = "ja7:v1"
_GROWTH_MAX_AGE_DAYS = 365
_MAX_QUOTE = 240

# signal kind -> (the gaps that must all be present, the gaps of which any suffices)
_GAP_KINDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "no_intake_channel": (("no_online_intake", "no_live_chat"), ()),
    "no_support_staff_listed": (("no_support_staff_listed",), ()),
    "stale_site": ((), ("stale_copyright", "stale_news")),
}

_PAIN_RE = re.compile(
    r"(?:\b(?:never|didn'?t|did\s+not|doesn'?t|does\s+not|won'?t|wouldn'?t|no\s+one|nobody)"
    r"(?!\s+(?:fail|hesitat|once|had\s+to|let|made|left\s+me\s+wondering))"
    r"(?:\s+\w+){0,2}\s+"
    r"(?:call(?:ed|s)?\s+(?:me\s+|us\s+)?back|return(?:ed|s)?\s+(?:my\s+|our\s+|a\s+)?"
    r"(?:calls?|phone\s+calls?|emails?|messages?)|respond(?:ed|s)?|repl(?:y|ied|ies)|"
    r"answer(?:ed|s)?(?:\s+the)?(?:\s+phone)?|hear(?:d)?\s+back|g[eo]t\s+back)"
    r"|\bunreturned\b|\bunresponsive\b"
    r"|\bno\s+(?:communication|response|call\s*back|follow[- ]?up)\b(?!\s+(?:issue|problem))"
    r"|\b(?:poor|lack\s+of|terrible|bad|zero|horrible)\s+communication\b"
    r"|\bhard\s+to\s+(?:reach|get\s+(?:a\s+)?hold\s+of|get\s+in\s+touch)"
    r"|\b(?:slow|weeks|months)\s+to\s+(?:respond|reply|return|get\s+back)"
    r"|\btook\s+(?:weeks|months|forever)\b"
    r"|\b(?:too\s+busy|understaffed|overwhelmed|short[- ]staffed)\b)",
    re.I,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_LAW_WORDS_RE = re.compile(
    r"\b(?:law|legal|attorney|attorneys|lawyer|lawyers|llp|llc|pllc|pc|p\.c\.|firm|group|"
    r"associates|office|offices|the|of|and|&)\b",
    re.I,
)


def firm_tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^a-z]+", _LAW_WORDS_RE.sub(" ", name.casefold())) if len(t) > 2}


def pain_sentence(text: str) -> tuple[str, str] | None:
    """(the sentence, the phrase that matched) for the first complaint about
    being unreachable in `text`, or None."""
    for sentence in _SENTENCE_SPLIT_RE.split(" ".join((text or "").split())):
        m = _PAIN_RE.search(sentence)
        if m:
            return sentence[:_MAX_QUOTE], m.group(0).lower()
    return None


def gap_kinds_present(gaps: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """The pain kinds the gap list supports, each with the gap entries behind it."""
    by_name = {g["gap"]: g for g in gaps if isinstance(g, dict) and g.get("gap")}
    out: dict[str, list[dict[str, Any]]] = {}
    for kind, (all_of, any_of) in _GAP_KINDS.items():
        if all_of and all(g in by_name for g in all_of):
            out[kind] = [by_name[g] for g in all_of]
        elif any_of and any(g in by_name for g in any_of):
            out[kind] = [by_name[g] for g in any_of if g in by_name]
    return out


def _fingerprint(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()  # noqa: S324 -- an id, not a secret


def _latest_claim(conn: Any, firm_id: Any, attr: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT value, source, observed_at FROM firm_attribute WHERE firm_id = %s "
            "AND attr = %s ORDER BY observed_at DESC LIMIT 1",
            (firm_id, attr),
        )
        return cur.fetchone()


def _sighting(conn: Any, signal_id: int, source: str, url: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO signal_sighting (signal_id, source, url, present, fetch_ok) "
            "VALUES (%s, %s, %s, true, true)",
            (signal_id, source, url),
        )


def _write(
    conn: Any, firm_id: Any, kind: str, fingerprint: str, first_seen: datetime,
    last_seen: datetime, evidence: dict[str, Any],
) -> bool:
    signal_id, inserted = _upsert_signal(
        conn, str(firm_id), kind, fingerprint, first_seen, last_seen, 0, evidence
    )
    if inserted:
        _sighting(conn, signal_id, evidence["source"], evidence.get("url"))
    return inserted


def _close_missing(conn: Any, firm_id: Any, open_kinds: set[str], now: datetime) -> int:
    closed = 0
    with conn.cursor() as cur:
        for kind in _GAP_KINDS:
            if kind in open_kinds:
                continue
            cur.execute(
                "UPDATE signal SET closed_at = %s WHERE firm_id = %s AND kind = %s "
                "AND closed_at IS NULL",
                (now, firm_id, kind),
            )
            closed += cur.rowcount
    return closed


def write_pain_signals(conn: Any, firm_id: Any, firm_name: str, claims: dict[str, dict]) -> dict:
    """Signals for one firm from its latest claims. Returns counts."""
    counts = {"inserted": 0, "closed": 0}
    now = datetime.now(UTC)

    gaps_claim = claims.get("site_gaps")
    present: dict[str, list[dict]] = {}
    if gaps_claim:
        present = gap_kinds_present(gaps_claim["value"] or [])
        seen = gaps_claim["observed_at"]
        for kind, entries in present.items():
            evidence = {
                "gaps": [e["gap"] for e in entries],
                "quote": "; ".join(str(e.get("evidence") or e["gap"]) for e in entries),
                "source": "site:page", "sources": ["site:page"], "url": None,
            }
            if _write(conn, firm_id, kind, _fingerprint(str(firm_id), kind), seen, seen, evidence):
                counts["inserted"] += 1
        counts["closed"] += _close_missing(conn, firm_id, set(present), now)

    snippets_claim = claims.get("search_review_snippets")
    if snippets_claim:
        seen = snippets_claim["observed_at"]
        tokens = firm_tokens(firm_name)
        for snippet in snippets_claim["value"] or []:
            if not isinstance(snippet, dict):
                continue
            text = f"{snippet.get('title') or ''}. {snippet.get('body') or ''}"
            if tokens and not any(t in text.casefold() for t in tokens):
                continue
            found = pain_sentence(text)
            if not found:
                continue
            quote, phrase = found
            url = snippet.get("url")
            evidence = {
                "quote": quote, "match": phrase, "url": url,
                "source": "search:ddg", "sources": ["search:ddg"],
            }
            fp = _fingerprint(str(firm_id), "review_unreturned_call", url or quote)
            if _write(conn, firm_id, "review_unreturned_call", fp, seen, seen, evidence):
                counts["inserted"] += 1

    growth_claim = claims.get("growth_news")
    if growth_claim:
        seen = growth_claim["observed_at"]
        cutoff = date.today() - timedelta(days=_GROWTH_MAX_AGE_DAYS)
        for post in growth_claim["value"] or []:
            if not isinstance(post, dict) or not post.get("url") or not post.get("date"):
                continue
            try:
                posted = date.fromisoformat(str(post["date"]))
            except ValueError:
                continue
            if posted < cutoff:
                continue
            first_seen = datetime(posted.year, posted.month, posted.day, tzinfo=UTC)
            evidence = {
                "headline": post.get("title"), "quote": post.get("title"), "url": post["url"],
                "date": post["date"], "cue": post.get("cue"),
                "source": "site:page", "sources": ["site:page"],
            }
            fp = _fingerprint(str(firm_id), "new_office_or_lateral", post["url"])
            if _write(conn, firm_id, "new_office_or_lateral", fp, first_seen,
                      max(first_seen, seen), evidence):
                counts["inserted"] += 1
    return counts


def _select_firm_ids(conn: Any, opts: dict[str, Any]) -> list[Any]:
    firm_ids_file = opts.get("firm_ids_file")
    if firm_ids_file:
        return [
            line.strip()
            for line in Path(str(firm_ids_file)).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    query = (
        "SELECT DISTINCT firm_id FROM firm_attribute WHERE attr IN "
        "('site_gaps', 'search_review_snippets', 'growth_news') ORDER BY firm_id"
    )
    params: list[Any] = []
    limit = opts.get("limit")
    if limit not in (None, ""):
        query += " LIMIT %s"
        params.append(int(limit))
    with conn.cursor() as cur:
        cur.execute(query, params)
        return [r["firm_id"] for r in cur.fetchall()]


@component(
    _COMPONENT, "JA",
    "Pain signals: site gaps, unreachable-firm reviews and growth news become intent",
)
def run(ctx: RunContext, **opts: Any) -> RunResult:
    conn = ctx.conn
    result = RunResult()
    inserted = closed = 0
    for firm_id in _select_firm_ids(conn, opts):
        try:
            claims = {
                attr: claim
                for attr in ("site_gaps", "search_review_snippets", "growth_news")
                if (claim := _latest_claim(conn, firm_id, attr)) is not None
            }
            if not claims:
                result.skipped += 1
                continue
            with conn.cursor() as cur:
                cur.execute("SELECT canonical_name FROM firm WHERE id = %s", (firm_id,))
                firm = cur.fetchone()
            if firm is None:
                result.skipped += 1
                continue
            payload = {
                attr: [c["value"], str(c["observed_at"])] for attr, c in claims.items()
            }
            input_hash = hashlib.sha256(
                (_VERSION + json.dumps(payload, sort_keys=True, default=str)).encode("utf-8")
            ).hexdigest()
            with ctx.once(_COMPONENT, str(firm_id), input_hash) as should_run:
                if not should_run:
                    result.skipped += 1
                    continue
                counts = write_pain_signals(conn, firm_id, firm["canonical_name"], claims)
                inserted += counts["inserted"]
                closed += counts["closed"]
            result.processed += 1
        except Exception as exc:  # noqa: BLE001 -- per-firm isolation, never global
            result.failed += 1
            result.notes.append(f"{_COMPONENT} firm={firm_id}: {exc}")
        ctx.checkpoint()
    result.notes.append(f"signals opened {inserted}, closed {closed}")
    return result
