"""Every alert in context/40-pipeline/07-observability.md. Most fire on
ABSENCE, not on an error -- a watcher that returns zero results does not
raise, it just quietly stops feeding the pipeline. **Every alert here is a
defect, not a metric to watch**: `firing` always means something is broken.

Each alert function is `(ctx, cfg) -> AlertOutcome`, returning one of three
states:
  ok       -- evaluated, within bounds.
  firing   -- evaluated, a defect. Never overridden by a flag.
  no_data  -- could NOT be evaluated (the table/snapshot history it needs is
              empty). Distinct from `ok` on purpose -- the absence of the
              data needed to check for absence is itself information, and
              collapsing it into `ok` would hide exactly the silent-failure
              mode this whole chunk exists to catch.

`evaluate_all` runs every alert and returns every outcome (never short-
circuits on the first firing one -- an operator needs the whole picture).
`write_alert_events` persists them to `alert_event` (sql/080_observe.sql).
The `alerts` component (plane "ops") is a thin wrapper the flow runner and
`lge run alerts` both use: RunResult.processed/skipped/failed count
ok/no_data/firing outcomes respectively, so "any firing" already means
`result.failed > 0` -- the same exit-code convention every other component
uses, with no special case needed.
"""

from __future__ import annotations

import difflib
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from lge.ops.config import AlertsConfig, load_alerts_config
from lge.ops.snapshot import (
    METRIC_BENCH_AVAILABLE,
    METRIC_FEE_CONF,
    METRIC_TIER_SHARE,
    latest,
    latest_before,
)
from lge.registry import RunContext, RunResult, component


@dataclass(frozen=True)
class AlertOutcome:
    name: str
    state: str  # ok | firing | no_data
    value: float | None
    detail: str


def _opt(cfg: AlertsConfig, alert: str, key: str, default: Any) -> Any:
    return cfg.alert(alert).get(key, default)


# =============================================================================
# Watcher silence -- JA1's last sweep produced 0 new postings across every
# qualified firm it swept.
# =============================================================================


def _watcher_silence(ctx: RunContext, cfg: AlertsConfig) -> AlertOutcome:
    name = "watcher_silence"
    window_h = float(_opt(cfg, name, "sweep_window_hours", 6))
    with ctx.conn.cursor() as cur:
        cur.execute("SELECT max(swept_at) AS d FROM careers_sweep")
        last = cur.fetchone()["d"]
    if last is None:
        return AlertOutcome(name, "no_data", None, "JA1 has never run -- no careers_sweep rows")

    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT coalesce(sum(postings_found), 0) AS n, count(*) AS swept "
            "FROM careers_sweep WHERE swept_at >= %s - (%s || ' hours')::interval",
            (last, window_h),
        )
        row = cur.fetchone()
    found, swept = row["n"], row["swept"]
    detail = f"last sweep ({last.isoformat()}): {found} new posting(s) across {swept} firm(s) swept"
    if found == 0:
        return AlertOutcome(
            name, "firing", 0,
            detail + " -- statistically impossible; parser broke or fetch is blocked",
        )
    return AlertOutcome(name, "ok", found, detail)


# =============================================================================
# Platform parser silence -- a bar-board platform yields zero across every
# one of its hosts.
# =============================================================================


def _platform_parser_silence(ctx: RunContext, cfg: AlertsConfig) -> AlertOutcome:
    name = "platform_parser_silence"
    window_days = int(_opt(cfg, name, "window_days", 7))
    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT platform, host FROM source_registry WHERE platform IS NOT NULL"
        )
        rows = cur.fetchall()
    if not rows:
        return AlertOutcome(name, "no_data", None, "no platform-tagged sources in source_registry")

    by_platform: dict[str, list[str]] = {}
    for r in rows:
        by_platform.setdefault(r["platform"], []).append(r["host"])

    silent: list[str] = []
    yields: dict[str, int] = {}
    for platform, hosts in by_platform.items():
        with ctx.conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM raw_posting "
                "WHERE source = ANY(%s) AND fetched_at >= now() - (%s || ' days')::interval",
                ([f"bar_board:{h}" for h in hosts], window_days),
            )
            n = cur.fetchone()["n"]
        yields[platform] = n
        if n == 0:
            silent.append(platform)

    if silent:
        detail = (
            f"platform(s) with zero yield across all boards in the last {window_days}d: "
            + ", ".join(sorted(silent))
        )
        return AlertOutcome(name, "firing", len(silent), detail)
    total = sum(yields.values())
    return AlertOutcome(
        name, "ok", total,
        f"all {len(by_platform)} platform(s) yielding in the last {window_days}d (total={total})",
    )


# =============================================================================
# Dedupe drift -- reuses g1_identity's duplicate-domain / duplicate-phone
# queries verbatim (D-014: these two are hard, always).
# =============================================================================


def _dedupe_drift(ctx: RunContext, cfg: AlertsConfig) -> AlertOutcome:
    name = "dedupe_drift"
    with ctx.conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM firm")
        total = cur.fetchone()["n"]
    if total == 0:
        return AlertOutcome(name, "no_data", None, "no firms yet -- resolve_identity has not run")

    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT domain FROM firm WHERE domain IS NOT NULL GROUP BY domain HAVING count(*) > 1"
        )
        domain_dupes = cur.fetchall()
        cur.execute(
            "SELECT phone_e164 FROM firm WHERE phone_e164 IS NOT NULL "
            "GROUP BY phone_e164 HAVING count(*) > 1"
        )
        phone_dupes = cur.fetchall()

    n = len(domain_dupes) + len(phone_dupes)
    if n > 0:
        return AlertOutcome(
            name, "firing", n,
            f"{len(domain_dupes)} duplicate-domain group(s), {len(phone_dupes)} "
            "duplicate-phone group(s) -- R1/R2 stopped firing",
        )
    return AlertOutcome(name, "ok", 0, "no firm shares a domain or phone with another")


# =============================================================================
# Week-over-week snapshot comparisons -- extraction confidence drop, tier
# distribution shift. Shared helper: today's snapshot vs the most recent one
# 5-9 days prior.
# =============================================================================


def _wow_pair(
    ctx: RunContext, metric: str, lookback_min: int, lookback_max: int
) -> tuple[datetime, dict[str, float], datetime, dict[str, float]] | None:
    cur_pair = latest(ctx, metric)
    if cur_pair is None:
        return None
    cur_day, cur_vals = cur_pair
    prev_pair = latest_before(ctx, metric, cur_day - timedelta(days=lookback_min - 1))
    if prev_pair is None:
        return None
    prev_day, prev_vals = prev_pair
    if prev_day < cur_day - timedelta(days=lookback_max):
        return None  # too far back to call it "a week ago"
    return cur_day, cur_vals, prev_day, prev_vals


def _extraction_confidence_drop(ctx: RunContext, cfg: AlertsConfig) -> AlertOutcome:
    name = "extraction_confidence_drop"
    drop_threshold = float(_opt(cfg, name, "drop_threshold", 0.1))
    lo = int(_opt(cfg, name, "lookback_days_min", 5))
    hi = int(_opt(cfg, name, "lookback_days_max", 9))

    pair = _wow_pair(ctx, METRIC_FEE_CONF, lo, hi)
    if pair is None:
        return AlertOutcome(
            name, "no_data", None,
            "no prior-week fee_model confidence snapshot to compare against yet",
        )
    cur_day, cur_vals, prev_day, prev_vals = pair

    drops = []
    for family, prev_conf in prev_vals.items():
        cur_conf = cur_vals.get(family)
        if cur_conf is None:
            continue
        drop = prev_conf - cur_conf
        if drop > drop_threshold:
            drops.append((family, prev_conf, cur_conf, drop))

    detail_days = f"{prev_day.date()} -> {cur_day.date()}"
    if drops:
        worst = max(drops, key=lambda d: d[3])
        detail = (
            f"{detail_days}: " + "; ".join(f"{f} {p:.2f}->{c:.2f}" for f, p, c, _d in drops)
        )
        return AlertOutcome(name, "firing", worst[3], detail)
    return AlertOutcome(
        name, "ok", 0.0, f"{detail_days}: no family dropped more than {drop_threshold}"
    )


def _tier_distribution_shift(ctx: RunContext, cfg: AlertsConfig) -> AlertOutcome:
    name = "tier_distribution_shift"
    shift_threshold = float(_opt(cfg, name, "shift_threshold", 0.15))
    lo = int(_opt(cfg, name, "lookback_days_min", 5))
    hi = int(_opt(cfg, name, "lookback_days_max", 9))

    pair = _wow_pair(ctx, METRIC_TIER_SHARE, lo, hi)
    if pair is None:
        return AlertOutcome(
            name, "no_data", None, "no prior-week tier-share snapshot to compare against yet"
        )
    cur_day, cur_vals, prev_day, prev_vals = pair

    all_tiers = set(cur_vals) | set(prev_vals)
    shifted = []
    for tier in all_tiers:
        delta = cur_vals.get(tier, 0.0) - prev_vals.get(tier, 0.0)
        if abs(delta) > shift_threshold:
            shifted.append((tier, prev_vals.get(tier, 0.0), cur_vals.get(tier, 0.0), delta))

    detail_days = f"{prev_day.date()} -> {cur_day.date()}"
    if shifted:
        worst = max(shifted, key=lambda s: abs(s[3]))
        detail = detail_days + ": " + "; ".join(f"{t} {p:.1%}->{c:.1%}" for t, p, c, _d in shifted)
        return AlertOutcome(name, "firing", abs(worst[3]), detail)
    return AlertOutcome(
        name, "ok", 0.0, f"{detail_days}: no tier moved more than {shift_threshold:.0%}"
    )


# =============================================================================
# Bounce rate -- delivery is out of scope for M10 (see build brief), so this
# reports no_data until outreach_touch rows carry a delivery outcome.
# =============================================================================


def _bounce_rate(ctx: RunContext, cfg: AlertsConfig) -> AlertOutcome:
    name = "bounce_rate"
    threshold = float(_opt(cfg, name, "threshold", 0.02))
    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT mailbox, count(*) AS n, count(*) FILTER (WHERE bounced) AS bounced "
            "FROM outreach_touch WHERE channel = 'email' AND bounced IS NOT NULL "
            "GROUP BY mailbox"
        )
        rows = cur.fetchall()
    if not rows:
        return AlertOutcome(
            name, "no_data", None,
            "no outreach_touch rows carry a delivery outcome yet -- delivery is out of "
            "scope for this milestone",
        )

    firing = []
    worst_rate = 0.0
    for r in rows:
        rate = r["bounced"] / r["n"] if r["n"] else 0.0
        worst_rate = max(worst_rate, rate)
        if rate > threshold:
            firing.append((r["mailbox"], rate, r["n"]))

    if firing:
        detail = "; ".join(f"{m}: {rate:.1%} of {n}" for m, rate, n in firing)
        return AlertOutcome(name, "firing", worst_rate, detail)
    return AlertOutcome(
        name, "ok", worst_rate, f"{len(rows)} mailbox(es), all under {threshold:.0%}"
    )


# =============================================================================
# Signal-to-contact latency -- p50 ARMED -> ENGAGED for STRIKE-band leads.
# =============================================================================

_LATENCY_SQL = """
WITH armed AS (
  SELECT lse.lead_id, lse.at AS armed_at
  FROM lead_state_event lse
  JOIN lead l ON l.id = lse.lead_id
  WHERE lse.to_state = 'ARMED' AND l.band = %(band)s
),
engaged AS (
  SELECT a.lead_id, a.armed_at, min(e.at) AS engaged_at
  FROM armed a
  JOIN lead_state_event e
    ON e.lead_id = a.lead_id AND e.to_state = 'ENGAGED' AND e.at > a.armed_at
  GROUP BY a.lead_id, a.armed_at
)
SELECT EXTRACT(EPOCH FROM (engaged_at - armed_at)) / 3600.0 AS hours FROM engaged
"""


def _signal_to_contact_latency(ctx: RunContext, cfg: AlertsConfig) -> AlertOutcome:
    name = "signal_to_contact_latency"
    band = str(_opt(cfg, name, "band", "STRIKE"))
    threshold_h = float(_opt(cfg, name, "p50_hours_threshold", 48))

    with ctx.conn.cursor() as cur:
        cur.execute(_LATENCY_SQL, {"band": band})
        hours = [float(r["hours"]) for r in cur.fetchall()]

    if not hours:
        return AlertOutcome(
            name, "no_data", None,
            f"no {band}-band lead has both an ARMED and a later ENGAGED lead_state_event yet",
        )

    p50 = statistics.median(hours)
    detail = f"p50={p50:.1f}h over {len(hours)} {band} lead(s)"
    if p50 > threshold_h:
        return AlertOutcome(name, "firing", p50, detail)
    return AlertOutcome(name, "ok", p50, detail)


# =============================================================================
# Bench starvation -- a wedge SKU at 0 availability for > 7 days, from
# observe_snapshot history (bench_inventory alone has no history).
# =============================================================================


def _bench_starvation(ctx: RunContext, cfg: AlertsConfig) -> AlertOutcome:
    name = "bench_starvation"
    zero_days_threshold = int(_opt(cfg, name, "zero_days_threshold", 7))

    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT dim FROM observe_snapshot WHERE metric = %s", (METRIC_BENCH_AVAILABLE,)
        )
        skus = [r["dim"] for r in cur.fetchall()]
    if not skus:
        return AlertOutcome(name, "no_data", None, "no bench_available snapshot history yet")

    starved: list[tuple[str, int]] = []
    max_streak = 0
    for sku in skus:
        with ctx.conn.cursor() as cur:
            cur.execute(
                "SELECT taken_at, value FROM observe_snapshot "
                "WHERE metric = %s AND dim = %s ORDER BY taken_at DESC",
                (METRIC_BENCH_AVAILABLE, sku),
            )
            rows = cur.fetchall()
        streak_start = None
        prev_day = None
        for r in rows:
            day, value = r["taken_at"], float(r["value"])
            if value != 0:
                break
            if prev_day is not None and (prev_day - day) > timedelta(days=1):
                break  # a gap in snapshots -- do not claim continuity across it
            streak_start = day
            prev_day = day
        if streak_start is not None:
            duration = (rows[0]["taken_at"] - streak_start).days
            max_streak = max(max_streak, duration)
            if duration > zero_days_threshold:
                starved.append((sku, duration))

    if starved:
        detail = "; ".join(f"{sku}: 0 for {d}d" for sku, d in starved)
        return AlertOutcome(name, "firing", max(d for _s, d in starved), detail)
    return AlertOutcome(name, "ok", max_streak, f"{len(skus)} sku(s) tracked, none starved")


# =============================================================================
# Bench staleness -- bench_inventory.as_of older than 48h. A stale bench is
# treated as empty (I4) -- this is what catches the sync itself going stale.
# =============================================================================


def _bench_staleness(ctx: RunContext, cfg: AlertsConfig) -> AlertOutcome:
    name = "bench_staleness"
    threshold_h = float(_opt(cfg, name, "hours_threshold", 48))

    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT sku, language, practice_exp, as_of, "
            "EXTRACT(EPOCH FROM (now() - as_of)) / 3600.0 AS age_h FROM bench_inventory"
        )
        rows = cur.fetchall()
    if not rows:
        return AlertOutcome(
            name, "no_data", None, "bench_inventory is empty -- bench_sync has not run"
        )

    stale = [r for r in rows if r["age_h"] > threshold_h]
    max_age = max(float(r["age_h"]) for r in rows)
    if stale:
        detail = "; ".join(
            f"{r['sku']}/{r['language']}/{r['practice_exp']}: {r['age_h']:.0f}h old" for r in stale
        )
        return AlertOutcome(name, "firing", max_age, detail)
    return AlertOutcome(
        name, "ok", max_age, f"{len(rows)} row(s), all under {threshold_h:.0f}h old"
    )


# =============================================================================
# Stale share -- > 20% of the qualified pool past 90-day freshness.
# =============================================================================


def _stale_share(ctx: RunContext, cfg: AlertsConfig) -> AlertOutcome:
    name = "stale_share"
    freshness_days = int(_opt(cfg, name, "freshness_days", 90))
    share_threshold = float(_opt(cfg, name, "share_threshold", 0.20))

    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM firm "
            "WHERE tier IS NOT NULL AND tier NOT LIKE 'DQ%%' AND tier <> 'UNCLASSIFIED'"
        )
        pool = cur.fetchone()["n"]
        cur.execute(
            "SELECT count(*) AS n FROM firm "
            "WHERE tier IS NOT NULL AND tier NOT LIKE 'DQ%%' AND tier <> 'UNCLASSIFIED' "
            "AND (last_crawled IS NULL OR last_crawled < now() - (%s || ' days')::interval)",
            (freshness_days,),
        )
        stale = cur.fetchone()["n"]

    if pool == 0:
        return AlertOutcome(name, "no_data", None, "no qualified (non-DQ, classified) firms yet")

    share = stale / pool
    detail = f"{stale}/{pool} ({share:.1%}) past {freshness_days}d freshness"
    if share > share_threshold:
        return AlertOutcome(name, "firing", share, detail)
    return AlertOutcome(name, "ok", share, detail)


# =============================================================================
# Source yield zero -- a checked, registered source with zero
# documents/postings referencing its host in the trailing window.
# =============================================================================


def _source_yield_zero(ctx: RunContext, cfg: AlertsConfig) -> AlertOutcome:
    name = "source_yield_zero"
    window_days = int(_opt(cfg, name, "window_days", 14))

    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT host FROM source_registry WHERE robots_checked IS NOT NULL"
        )
        hosts = [r["host"] for r in cur.fetchall()]
    if not hosts:
        return AlertOutcome(name, "no_data", None, "no checked sources in source_registry yet")

    zero_yield: list[str] = []
    total_yield = 0
    for host in hosts:
        like = f"%{host}%"
        with ctx.conn.cursor() as cur:
            cur.execute(
                "SELECT "
                "  (SELECT count(*) FROM raw_posting "
                "     WHERE (source ILIKE %(like)s OR source_url ILIKE %(like)s) "
                "       AND fetched_at >= now() - (%(days)s || ' days')::interval"
                "       AND fetch_ok) AS postings, "
                "  (SELECT count(*) FROM document "
                "     WHERE url ILIKE %(like)s "
                "       AND fetched_at >= now() - (%(days)s || ' days')::interval"
                "       AND fetch_ok) AS documents",
                {"like": like, "days": window_days},
            )
            row = cur.fetchone()
        n = row["postings"] + row["documents"]
        total_yield += n
        if n == 0:
            zero_yield.append(host)

    if zero_yield:
        detail = (
            f"host(s) with zero documents/postings in the last {window_days}d despite "
            "having been checked: " + ", ".join(sorted(zero_yield))
            + " -- check robots.txt before assuming the parser broke"
        )
        return AlertOutcome(name, "firing", len(zero_yield), detail)
    return AlertOutcome(name, "ok", total_yield, f"{len(hosts)} host(s) checked, all yielding")


# =============================================================================
# Robots diff -- latest robots_snapshot vs previous, for any host, touching
# job paths / crawl-delay / agent rules.
# =============================================================================


def _robots_relevant_change(old: str, new: str, keywords: list[str]) -> str | None:
    old_lines = (old or "").splitlines()
    new_lines = (new or "").splitlines()
    diff_lines = [
        ln[1:].strip()
        for ln in difflib.unified_diff(old_lines, new_lines, n=0, lineterm="")
        if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))
    ]
    for ln in diff_lines:
        low = ln.lower()
        if low.startswith("crawl-delay") or low.startswith("user-agent"):
            return ln
        if any(kw.lower() in low for kw in keywords):
            return ln
    return None


def _robots_diff(ctx: RunContext, cfg: AlertsConfig) -> AlertOutcome:
    name = "robots_diff"
    keywords = list(_opt(cfg, name, "job_path_keywords", ["career", "job", "apply"]))

    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT host, count(*) AS n FROM robots_snapshot GROUP BY host HAVING count(*) >= 2"
        )
        hosts = [r["host"] for r in cur.fetchall()]
    if not hosts:
        return AlertOutcome(
            name, "no_data", None, "fewer than 2 robots_snapshot rows for any host yet"
        )

    changed: list[str] = []
    for host in hosts:
        with ctx.conn.cursor() as cur:
            cur.execute(
                "SELECT robots_txt FROM robots_snapshot WHERE host = %s "
                "ORDER BY taken_at DESC LIMIT 2",
                (host,),
            )
            rows = cur.fetchall()
        newer, older = rows[0]["robots_txt"] or "", rows[1]["robots_txt"] or ""
        hit = _robots_relevant_change(older, newer, keywords)
        if hit is not None:
            changed.append(f"{host}: {hit!r}")

    if changed:
        return AlertOutcome(
            name, "firing", len(changed),
            "job-path/crawl-delay/agent-rule change since the last snapshot: " + "; ".join(changed),
        )
    return AlertOutcome(name, "ok", 0, f"{len(hosts)} host(s) with history, no job-relevant change")


# =============================================================================
# Agency rule-3 spike -- geographic_spread rejects this week vs trailing
# 4-week average.
# =============================================================================


def _agency_rule3_spike(ctx: RunContext, cfg: AlertsConfig) -> AlertOutcome:
    name = "agency_rule3_spike"
    multiplier_threshold = float(_opt(cfg, name, "multiplier_threshold", 3.0))
    week_days = int(_opt(cfg, name, "week_days", 7))
    trailing_weeks = int(_opt(cfg, name, "trailing_weeks", 4))

    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM job_posting_rejected "
            "WHERE rule = 'geographic_spread' "
            "AND rejected_at >= now() - (%s || ' days')::interval",
            (week_days,),
        )
        this_week = cur.fetchone()["n"]

        weekly_counts = []
        for w in range(1, trailing_weeks + 1):
            cur.execute(
                "SELECT count(*) AS n FROM job_posting_rejected "
                "WHERE rule = 'geographic_spread' "
                "AND rejected_at >= now() - (%s || ' days')::interval "
                "AND rejected_at <  now() - (%s || ' days')::interval",
                (week_days * (w + 1), week_days * w),
            )
            weekly_counts.append(cur.fetchone()["n"])

    if this_week == 0 and sum(weekly_counts) == 0:
        return AlertOutcome(
            name, "no_data", None,
            "no geographic_spread rejects in this week or the trailing "
            f"{trailing_weeks} week(s) -- nothing to compare",
        )

    baseline = sum(weekly_counts) / trailing_weeks if trailing_weeks else 0.0
    detail = f"this week={this_week}, trailing {trailing_weeks}-week avg={baseline:.1f}"

    if baseline == 0:
        if this_week > 0:
            return AlertOutcome(
                name, "firing", float(this_week), detail + " -- new rejects with no baseline at all"
            )
        return AlertOutcome(name, "ok", 0.0, detail)

    multiplier = this_week / baseline
    if multiplier > multiplier_threshold:
        return AlertOutcome(name, "firing", multiplier, detail + f" ({multiplier:.1f}x)")
    return AlertOutcome(name, "ok", multiplier, detail + f" ({multiplier:.1f}x)")


# =============================================================================
# Registry + evaluation
# =============================================================================

_ALERTS: list[tuple[str, Any]] = [
    ("watcher_silence", _watcher_silence),
    ("platform_parser_silence", _platform_parser_silence),
    ("dedupe_drift", _dedupe_drift),
    ("extraction_confidence_drop", _extraction_confidence_drop),
    ("tier_distribution_shift", _tier_distribution_shift),
    ("bounce_rate", _bounce_rate),
    ("signal_to_contact_latency", _signal_to_contact_latency),
    ("bench_starvation", _bench_starvation),
    ("bench_staleness", _bench_staleness),
    ("stale_share", _stale_share),
    ("source_yield_zero", _source_yield_zero),
    ("robots_diff", _robots_diff),
    ("agency_rule3_spike", _agency_rule3_spike),
]


def evaluate_all(ctx: RunContext, cfg: AlertsConfig | None = None) -> list[AlertOutcome]:
    cfg = cfg or load_alerts_config()
    outcomes = []
    for name, fn in _ALERTS:
        try:
            outcomes.append(fn(ctx, cfg))
        except Exception as exc:  # an alert that cannot evaluate is itself a defect
            ctx.log.exception("alert %r raised while evaluating", name)
            outcomes.append(AlertOutcome(name, "firing", None, f"alert raised {exc!r}"))
    return outcomes


def write_alert_events(ctx: RunContext, outcomes: list[AlertOutcome]) -> None:
    with ctx.conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO alert_event (alert, state, detail, value) VALUES (%s, %s, %s, %s)",
            [(o.name, o.state, o.detail, o.value) for o in outcomes],
        )


@component("alerts", "ops", "Evaluate every observability alert and record the results.")
def alerts_component(ctx: RunContext, **opts: Any) -> RunResult:
    outcomes = evaluate_all(ctx)
    write_alert_events(ctx, outcomes)
    ctx.checkpoint()

    result = RunResult()
    for o in outcomes:
        if o.state == "firing":
            result.failed += 1
        elif o.state == "no_data":
            result.skipped += 1
        else:
            result.processed += 1
        result.notes.append(f"{o.name}: {o.state} ({o.detail})")
    return result
