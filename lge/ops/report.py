"""`lge report attribution` -- context/40-pipeline/07-observability.md
"Attribution closes the loop": every WON/LOST lead carries its
`arming_signal`, and the join outcome x arming-signal-kind x tier is the
only mechanism that turns a `seeded` scoring weight in this system into a
`measured` one (context/40-pipeline/05-lead-lifecycle.md, "What decides
whether any of this was right"). Delivery/outreach is out of scope for
M10, so a fresh environment has no WON/LOST rows to report on yet -- the
query existing and being correct is the deliverable, not a populated
result today.
"""

from __future__ import annotations

from dataclasses import dataclass

from lge.registry import RunContext

_ATTRIBUTION_SQL = """
SELECT l.state AS outcome,
       coalesce(s.kind, '(none)') AS signal_kind,
       coalesce(f.tier, 'UNCLASSIFIED') AS tier,
       count(*) AS n
FROM lead l
JOIN firm f ON f.id = l.firm_id
LEFT JOIN signal s ON s.id = l.arming_signal
WHERE l.state IN ('WON', 'LOST')
GROUP BY l.state, coalesce(s.kind, '(none)'), coalesce(f.tier, 'UNCLASSIFIED')
ORDER BY l.state, n DESC
"""


@dataclass(frozen=True)
class AttributionRow:
    outcome: str
    signal_kind: str
    tier: str
    n: int


def attribution_report(ctx: RunContext) -> list[AttributionRow]:
    """outcome (WON/LOST) x arming-signal kind x tier, from lead + signal +
    firm. Every closed deal traces to the signal that surfaced it
    (context/40-pipeline/05-lead-lifecycle.md) -- `(none)` for the rare
    lead closed without ever being armed via a signal."""
    with ctx.conn.cursor() as cur:
        cur.execute(_ATTRIBUTION_SQL)
        rows = cur.fetchall()
    return [AttributionRow(r["outcome"], r["signal_kind"], r["tier"], r["n"]) for r in rows]
