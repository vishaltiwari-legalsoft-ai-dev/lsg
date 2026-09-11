"""coverage_report + the g7_coverage gate.

Summarizes what the purchased dataset (source=internal_firms) resolved into `firm`.
Deliberately does NOT compute "dataset vs Places" overlap: D1 (the Places harvest)
has not run in this environment, so that number does not exist yet. Stating that
honestly -- "unknown", never "the dataset looks complete so we narrowed discovery" --
is G7 (context/60-execution/03-hard-gates.md): discovery scope is reduced only on
numbers, never assumption. See context/50-first-party/04-firm-dataset.md's coverage
analysis (in dataset only / in Places only / in both / dataset x ICP tiers).
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime

from lge.registry import RunContext, RunResult, component, gate
from lge.settings import PROJECT_ROOT

SOURCE = "internal_firms"
_REPORT_PATH = PROJECT_ROOT / "data" / "out" / "coverage_report.md"

_PLACES_NOTE = (
    "Places harvest not yet run -- dataset-only / Places-only / overlap cannot be "
    "computed until D1 runs. This is reported as **unknown**, not as evidence the "
    "dataset is complete -- see G7 (context/60-execution/03-hard-gates.md)."
)


def _resolved_firm_ids(cur) -> list[str]:
    cur.execute(
        "SELECT DISTINCT firm_id FROM observation WHERE source = %s AND firm_id IS NOT NULL",
        (SOURCE,),
    )
    return [str(r["firm_id"]) for r in cur.fetchall()]


def _bucket(n: int) -> str:
    if n == 1:
        return "1"
    if n <= 3:
        return "2-3"
    if n <= 10:
        return "4-10"
    return "11+"


def _build_report(cur) -> str:
    firm_ids = _resolved_firm_ids(cur)
    n_resolved = len(firm_ids)

    n_with_domain = 0
    tier_dist: list[dict] = []
    if firm_ids:
        cur.execute(
            "SELECT count(*) AS n FROM firm WHERE id = ANY(%s) AND domain IS NOT NULL",
            (firm_ids,),
        )
        n_with_domain = cur.fetchone()["n"]
        cur.execute(
            "SELECT tier, count(*) AS n FROM firm WHERE id = ANY(%s) GROUP BY tier "
            "ORDER BY n DESC",
            (firm_ids,),
        )
        tier_dist = cur.fetchall()

    cur.execute("SELECT count(*) AS n FROM firm")
    total_firms = cur.fetchone()["n"]

    cur.execute(
        "SELECT count(*) AS n FROM contact c WHERE c.source = %s GROUP BY c.firm_id",
        (SOURCE,),
    )
    per_firm_counts = [r["n"] for r in cur.fetchall()]

    cur.execute("SELECT count(*) AS n FROM firm WHERE entity_kind = 'gov'")
    n_gov = cur.fetchone()["n"]

    cur.execute(
        "SELECT count(*) AS n FROM firm_attribute "
        "WHERE attr = 'vendor_size_contradiction' AND source = %s",
        (SOURCE,),
    )
    n_contradictions = cur.fetchone()["n"]

    cur.execute(
        "SELECT count(*) AS n FROM firm_attribute WHERE attr = 'cms_detected' AND source = %s",
        (SOURCE,),
    )
    n_cms = cur.fetchone()["n"]

    cur.execute(
        "SELECT value #>> '{}' AS slug, count(*) AS n FROM firm_attribute "
        "WHERE attr = 'primary_practice' AND source = %s GROUP BY slug ORDER BY n DESC",
        (SOURCE,),
    )
    practice_dist = cur.fetchall()

    lines: list[str] = []
    lines.append("# Coverage report -- internal_firms")
    lines.append("")
    lines.append(f"Generated: {datetime.now(UTC).isoformat()}")
    lines.append("")

    lines.append("## Resolution")
    lines.append(f"- Firms resolved from internal_firms observations: {n_resolved}")
    lines.append(f"- Of those, firms with a website domain (firm.domain IS NOT NULL): "
                  f"{n_with_domain}")
    lines.append(f"- Total firms in `firm` (all sources): {total_firms}")
    lines.append("")

    lines.append("## Contacts per firm (`contact`, source=internal_firms)")
    if per_firm_counts:
        buckets: dict[str, int] = {}
        for n in per_firm_counts:
            buckets[_bucket(n)] = buckets.get(_bucket(n), 0) + 1
        lines.append(f"- firms with >=1 contact: {len(per_firm_counts)}")
        lines.append(
            f"- min / median / max contacts per firm: {min(per_firm_counts)} / "
            f"{statistics.median(per_firm_counts)} / {max(per_firm_counts)}"
        )
        for label in ("1", "2-3", "4-10", "11+"):
            if label in buckets:
                lines.append(f"  - {label} contacts: {buckets[label]} firm(s)")
    else:
        lines.append("- no contacts loaded yet (run i1_contacts)")
    lines.append("")

    lines.append("## Entity kind")
    lines.append(f"- entity_kind = 'gov': {n_gov}")
    lines.append("")

    lines.append("## Size contradictions")
    lines.append(
        f"- firms where the vendor's own contact count contradicts its stated "
        f"'1 to 10' employee range: {n_contradictions}"
    )
    lines.append("")

    lines.append("## Legal case-management tooling")
    lines.append(f"- firms with a vendor-tag CMS claim (cms_detected): {n_cms}")
    lines.append("")

    lines.append("## Practice-area distribution (from vendor Description text)")
    if practice_dist:
        lines.append("| practice | firms |")
        lines.append("|---|---|")
        for r in practice_dist:
            lines.append(f"| {r['slug']} | {r['n']} |")
    else:
        lines.append("- no primary_practice claims yet (run i1_claims)")
    lines.append("")

    lines.append("## Places overlap")
    lines.append(_PLACES_NOTE)
    lines.append("")

    lines.append("## Dataset x ICP tiers")
    if any(r["tier"] is not None for r in tier_dist):
        lines.append("| tier | firms |")
        lines.append("|---|---|")
        for r in tier_dist:
            lines.append(f"| {r['tier'] or '(null)'} | {r['n']} |")
    else:
        lines.append("not yet classified -- no firm.tier values are set")
    lines.append("")

    return "\n".join(lines)


@component(
    "coverage_report",
    "i",
    "Write data/out/coverage_report.md summarizing the internal_firms load.",
)
def coverage_report(ctx: RunContext, **opts: object) -> RunResult:
    with ctx.conn.cursor() as cur:
        report = _build_report(cur)

    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH.write_text(report, encoding="utf-8")

    return RunResult(processed=1, notes=[f"wrote {_REPORT_PATH}"])


@gate("g7_coverage")
def g7_coverage(ctx: RunContext) -> tuple[bool, str]:
    if not _REPORT_PATH.is_file():
        return False, f"g7_coverage: {_REPORT_PATH} does not exist -- run coverage_report first"

    report_mtime = datetime.fromtimestamp(_REPORT_PATH.stat().st_mtime, tz=UTC)
    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT max(fetched_at) AS latest FROM observation WHERE source = %s", (SOURCE,)
        )
        row = cur.fetchone()
    latest_fetched = row["latest"] if row else None

    if latest_fetched is not None and report_mtime < latest_fetched:
        return False, (
            f"g7_coverage: report at {_REPORT_PATH} predates the latest {SOURCE} load "
            f"({latest_fetched}) -- regenerate coverage_report"
        )

    text = _REPORT_PATH.read_text(encoding="utf-8")
    if "Places harvest not yet run" not in text and "overlap cannot be computed" not in text:
        return False, (
            "g7_coverage: report does not state the Places overlap as unknown -- G7 "
            "requires discovery scope to be reduced only on numbers, never assumption"
        )

    return True, f"g7_coverage: {_REPORT_PATH} is current and states Places overlap as unknown"
