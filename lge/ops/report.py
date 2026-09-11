"""`lge report attribution` -- context/40-pipeline/07-observability.md
"Attribution closes the loop": every WON/LOST lead carries its
`arming_signal`, and the join outcome x arming-signal-kind x tier is the
only mechanism that turns a `seeded` scoring weight in this system into a
`measured` one (context/40-pipeline/05-lead-lifecycle.md, "What decides
whether any of this was right"). Delivery/outreach is out of scope for
M10, so a fresh environment has no WON/LOST rows to report on yet -- the
query existing and being correct is the deliverable, not a populated
result today.

Extended for the UI (plan/api-contract.md's outcome POST): most leads
cannot legally reach HANDOFF -> WON/LOST today (I4 -- the bench is empty),
so `lead.state` alone would under-count every won/lost deal an SDR records
through the API but the state machine refused to apply. `lead_outcome`
(sql/090_ui.sql) is append-only and always written regardless of whether
the transition applied, so it is unioned in here -- one row per lead's most
recent won/lost outcome, taking `lead.state` when the transition DID apply
(so a lead recorded WON via both `lead.state` and a `lead_outcome` row is
counted once, not twice) and falling back to `lead_outcome` otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass

from lge.registry import RunContext

_ATTRIBUTION_SQL = """
WITH latest_outcome AS (
  -- One row per lead: its most recently recorded won/lost lead_outcome,
  -- if any. DISTINCT ON needs the ORDER BY to start with the DISTINCT
  -- column (lead_id), so recency is broken by `at` then `id`.
  SELECT DISTINCT ON (lead_id) lead_id, action
  FROM lead_outcome
  WHERE action IN ('won', 'lost')
  ORDER BY lead_id, at DESC, id DESC
),
effective AS (
  SELECT
    l.id AS lead_id,
    l.firm_id,
    l.arming_signal,
    CASE WHEN l.state IN ('WON', 'LOST') THEN l.state ELSE upper(lo.action) END AS outcome
  FROM lead l
  LEFT JOIN latest_outcome lo ON lo.lead_id = l.id
  WHERE l.state IN ('WON', 'LOST') OR lo.action IS NOT NULL
)
SELECT e.outcome,
       coalesce(s.kind, '(none)') AS signal_kind,
       coalesce(f.tier, 'UNCLASSIFIED') AS tier,
       count(*) AS n
FROM effective e
JOIN firm f ON f.id = e.firm_id
LEFT JOIN signal s ON s.id = e.arming_signal
GROUP BY e.outcome, coalesce(s.kind, '(none)'), coalesce(f.tier, 'UNCLASSIFIED')
ORDER BY e.outcome, n DESC
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
