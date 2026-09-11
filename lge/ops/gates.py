"""`g3_tier_distribution` -- context/60-execution/03-hard-gates.md G3, sitting
between reconcile_and_class and resolve_contacts in the profile_probe flow
(config/flows.yml). Hard: R1 is a paid enricher, so a drifted classifier
spending its budget on the wrong firms is exactly what this gate exists to
stop before it happens (context/40-pipeline/06-orchestration.md "the gate
that must not be advisory" is written about G1, but the same economics
apply here -- resolve_contacts is spent per-firm, same as everything else).

Two ways to fail, both from the M10 build brief and config/alerts.yml's
`gates.g3_tier_distribution`:
  1. Every classified firm landed in one tier -- "classified" excludes
     tiers in `exempt_tiers` (UNCLASSIFIED by default), so a pre-crawl
     universe that is honestly all UNCLASSIFIED passes; the check only
     engages once `min_firms_for_uniformity_check` firms have an actual
     verdict.
  2. A previous observe_snapshot exists AND any tier's share moved more
     than `shift_threshold` since it.
Neither condition present -> PASS, distribution printed either way.
"""

from __future__ import annotations

from lge.ops.config import load_alerts_config
from lge.ops.snapshot import METRIC_TIER_SHARE, latest
from lge.registry import RunContext, gate


def _current_tier_counts(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT coalesce(tier, 'UNCLASSIFIED') AS tier, count(*) AS n FROM firm GROUP BY 1"
        )
        return {r["tier"]: r["n"] for r in cur.fetchall()}


def _format_distribution(counts: dict[str, int], total: int) -> str:
    lines = ["tier distribution:"]
    for tier, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        share = n / total if total else 0.0
        lines.append(f"  {tier:16} {n:6}  ({share:.1%})")
    return "\n".join(lines)


@gate("g3_tier_distribution")
def g3_tier_distribution(ctx: RunContext) -> tuple[bool, str]:
    cfg = load_alerts_config().gates_g3
    counts = _current_tier_counts(ctx.conn)
    total = sum(counts.values())
    dist_report = _format_distribution(counts, total)

    if total == 0:
        return True, "g3_tier_distribution: PASS -- no firms yet\n" + dist_report

    classified = {t: n for t, n in counts.items() if t not in cfg.exempt_tiers}
    classified_total = sum(classified.values())

    if classified_total >= cfg.min_firms_for_uniformity_check:
        non_zero_tiers = [t for t, n in classified.items() if n > 0]
        if len(non_zero_tiers) == 1:
            return False, (
                f"g3_tier_distribution: FAIL -- all {classified_total} classified firm(s) "
                f"landed in tier {non_zero_tiers[0]!r}. Either the classifier drifted or "
                f"the harvest changed shape (context/60-execution/03-hard-gates.md G3).\n"
                + dist_report
            )

    previous = latest(ctx, METRIC_TIER_SHARE)
    if previous is not None:
        prev_day, prev_shares = previous
        shifted = []
        for tier, n in counts.items():
            cur_share = n / total
            prev_share = prev_shares.get(tier, 0.0)
            if abs(cur_share - prev_share) > cfg.shift_threshold:
                shifted.append((tier, prev_share, cur_share))
        if shifted:
            detail = "; ".join(f"{t}: {p:.1%} -> {c:.1%}" for t, p, c in shifted)
            return False, (
                f"g3_tier_distribution: FAIL -- tier share moved more than "
                f"{cfg.shift_threshold:.0%} vs the snapshot from {prev_day.date()}: {detail}\n"
                + dist_report
            )

    return True, "g3_tier_distribution: PASS\n" + dist_report
