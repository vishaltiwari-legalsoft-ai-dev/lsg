"""Gate G2 -- context/60-execution/03-hard-gates.md: nothing widens beyond
the probe until 50 hand-checked firms are accurate on every attribute.
Shared by `GET /api/today` (the pending-review count in `attention.queues`)
and `GET /api/handcheck` (the full sample + accuracy rollup) so the two
never disagree about how many firms still need a look.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from lge.api.attributes import build_attributes_for_firm
from lge.api.labels import attr_label
from lge.score.reconcile import load_precedence

SAMPLE_SIZE = 50
GATE_RULE = (
    f"Passes when all {SAMPLE_SIZE} sampled firms have every shown attribute "
    "reviewed, and every review says correct -- 'accurate on every attribute'."
)


def sample_firms(conn: Any) -> list[dict]:
    """Firms with >=1 fetched document, ordered by a hash of the firm id --
    deterministic and stable across calls (never by recency, which would
    reshuffle the sample every time a new document is fetched)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT f.id, f.canonical_name AS name, f.domain
            FROM firm f
            WHERE EXISTS (SELECT 1 FROM document d WHERE d.firm_id = f.id)
            ORDER BY md5(f.id::text) ASC
            LIMIT %s
            """,
            (SAMPLE_SIZE,),
        )
        return cur.fetchall()


def compute_gate(conn: Any) -> dict[str, Any]:
    """Lightweight (no attribute-row rendering): counts distinct claimed
    attrs vs. distinct reviewed attrs per sampled firm directly in SQL."""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH sample AS (
              SELECT f.id FROM firm f
              WHERE EXISTS (SELECT 1 FROM document d WHERE d.firm_id = f.id)
              ORDER BY md5(f.id::text) ASC LIMIT %(n)s
            ),
            claimed AS (
              SELECT firm_id, count(DISTINCT attr) AS n_attrs
              FROM firm_attribute WHERE firm_id IN (SELECT id FROM sample)
              GROUP BY firm_id
            ),
            reviewed AS (
              SELECT firm_id, count(DISTINCT attr) AS n_reviewed, bool_and(correct) AS all_correct
              FROM handcheck_result WHERE firm_id IN (SELECT id FROM sample)
              GROUP BY firm_id
            )
            SELECT s.id, coalesce(c.n_attrs, 0) AS n_attrs,
                   coalesce(r.n_reviewed, 0) AS n_reviewed,
                   coalesce(r.all_correct, true) AS all_correct
            FROM sample s
            LEFT JOIN claimed c ON c.firm_id = s.id
            LEFT JOIN reviewed r ON r.firm_id = s.id
            """,
            {"n": SAMPLE_SIZE},
        )
        rows = cur.fetchall()

    sample_count = len(rows)
    fully_reviewed = [r for r in rows if r["n_attrs"] > 0 and r["n_reviewed"] >= r["n_attrs"]]
    reviewed_firms = len(fully_reviewed)
    every_review_correct = all(r["all_correct"] for r in fully_reviewed)
    passed = sample_count >= SAMPLE_SIZE and reviewed_firms >= SAMPLE_SIZE and every_review_correct

    return {
        "needed": SAMPLE_SIZE, "reviewed_firms": reviewed_firms,
        "passed": passed, "rule": GATE_RULE,
    }


def pending_count(conn: Any) -> int:
    gate = compute_gate(conn)
    return max(0, gate["needed"] - gate["reviewed_firms"])


def build_handcheck_response(conn: Any) -> dict[str, Any]:
    at = datetime.now(UTC)
    cfg = load_precedence()
    firms = sample_firms(conn)

    accuracy_checked: dict[str, int] = {}
    accuracy_correct: dict[str, int] = {}
    sample: list[dict[str, Any]] = []

    for f in firms:
        firm_id = f["id"]
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM firm WHERE id = %s", (firm_id,))
            firm_row = dict(cur.fetchone())
        firm_row["firm_id"] = firm_row["id"]
        attributes = build_attributes_for_firm(conn, firm_row, cfg, at)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT attr, correct, corrected_value FROM handcheck_result WHERE firm_id = %s",
                (firm_id,),
            )
            reviews = {
                r["attr"]: {"correct": r["correct"], "corrected_value": r["corrected_value"]}
                for r in cur.fetchall()
            }

        for attr_row in attributes:
            accuracy_checked.setdefault(attr_row.attr, 0)
            accuracy_correct.setdefault(attr_row.attr, 0)
            review = reviews.get(attr_row.attr)
            if review is not None:
                accuracy_checked[attr_row.attr] += 1
                if review["correct"]:
                    accuracy_correct[attr_row.attr] += 1

        sample.append(
            {
                "firm_id": str(firm_id), "name": f["name"], "domain": f["domain"],
                "attributes": attributes, "reviews": reviews,
            }
        )

    accuracy = [
        {
            "attr": attr, "label": attr_label(attr),
            "checked": accuracy_checked[attr], "correct": accuracy_correct[attr],
        }
        for attr in accuracy_checked
    ]

    return {"gate": compute_gate(conn), "accuracy": accuracy, "sample": sample}
