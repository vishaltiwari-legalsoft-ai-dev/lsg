"""Which column is which -- the seam (brain/plan/plan-v2.md, "the seams").

Two readers stand behind one interface. The rule reader is the header-and-
value sniffer (`lge.ingest.sniff`), keyless and instant. The LLM reader asks
the model once per sheet and then holds its answer to the same value checks:
a typed field (email, website, phone, dates, yes/no, sizes) the cells do not
look like is not adopted, the rules' reading of that column stands, and the
disagreement is written into the guess's reason so a person can see it.
Either way the result is one `ColumnMap`, so nothing downstream knows or
cares which reader ran. `settings.column_reader_name()` picks.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from lge.ingest.sniff import (
    _STRONG_SHAPES,
    SAMPLE_SIZE,
    ColumnMap,
    _assemble,
    shape_guess,
    sniff_columns,
)
from lge.ingest.vocab import BY_NAME, ColumnGuess, field_label_of
from lge.settings import Settings, get_settings

logger = logging.getLogger("lge.ingest.columns")

# the AI's answer is only trusted from here up; below it the column stays unmapped
MIN_LLM_CONFIDENCE = 0.5
# a rule guess this sure fills a column the AI left null
RULE_RESCUE_CONFIDENCE = 0.9


class ColumnReader(Protocol):
    name: str

    def read(self, headers: list[str], rows: list[dict[str, str]]) -> ColumnMap: ...


class RuleColumnReader:
    name = "rules"

    def read(self, headers: list[str], rows: list[dict[str, str]]) -> ColumnMap:
        return sniff_columns(headers, rows)


# (headers, sample_rows, api_key) -> SheetRead; injectable so tests never call out
SheetReadFn = Callable[..., object]


class LLMColumnReader:
    name = "llm"

    def __init__(self, api_key: str, call: SheetReadFn | None = None) -> None:
        self._api_key = api_key
        self._call = call

    def read(self, headers: list[str], rows: list[dict[str, str]]) -> ColumnMap:
        rules = sniff_columns(headers, rows)
        if not headers:
            return rules
        call = self._call
        if call is None:
            from lge.llm.sheet_reader import read_sheet

            call = read_sheet
        try:
            sheet = call(headers, rows[:SAMPLE_SIZE], api_key=self._api_key)
        except Exception as exc:  # noqa: BLE001 -- the rules are the fallback, never a crash
            logger.warning("sheet reader unavailable, rules used: %s: %s", type(exc).__name__, exc)
            return _assemble(
                rules.guesses, reader="rules",
                notes=[
                    f"The AI reader was unavailable ({type(exc).__name__}); "
                    "the rules read the sheet."
                ],
            )
        guesses, notes = reconcile(headers, rows, sheet, rules)
        return _assemble(guesses, reader="llm", notes=list(getattr(sheet, "notes", [])) + notes)


def reconcile(
    headers: list[str], rows: list[dict[str, str]], sheet: object, rules: ColumnMap
) -> tuple[list[ColumnGuess], list[str]]:
    """The AI's proposal against the rules and the values, column by column."""
    by_rules = {g.column: g for g in rules.guesses}
    proposed: dict[str, object] = {}
    for c in getattr(sheet, "columns", []):
        proposed.setdefault(getattr(c, "column", ""), c)  # a header named twice: first wins
    sample = rows[:SAMPLE_SIZE]
    out: list[ColumnGuess] = []
    notes: list[str] = []
    for h in headers:
        rule = by_rules[h]
        samples = rule.samples
        llm = proposed.get(h)
        llm_field = getattr(llm, "field", None) if llm is not None else None
        llm_conf = float(getattr(llm, "confidence", 0.0) or 0.0) if llm is not None else 0.0
        llm_reason = str(getattr(llm, "reason", "") or "").strip() if llm is not None else ""

        if llm is None:
            out.append(_rescue_or_none(rule, "the AI did not read this column", samples))
            continue
        if llm_field is None or llm_conf < MIN_LLM_CONFIDENCE:
            why = llm_reason or "the AI was unsure"
            out.append(_rescue_or_none(rule, f"AI: {why}", samples))
            continue
        if llm_field not in BY_NAME:
            notes.append(f"The AI named an unknown field '{llm_field}' for '{h}'; ignored.")
            out.append(_rescue_or_none(rule, f"AI named an unknown field ({llm_field})", samples))
            continue
        if llm_field in _STRONG_SHAPES:
            values = [r.get(h, "") for r in sample]
            sg = shape_guess(values)
            if sg is None or sg[0] != llm_field:
                label = field_label_of(llm_field)
                out.append(ColumnGuess(
                    h, rule.field, rule.confidence,
                    f"AI said {label}, the values do not look like it; {rule.reason}", samples,
                ))
                continue
        out.append(
            ColumnGuess(h, llm_field, max(0.0, min(1.0, llm_conf)), f"AI: {llm_reason}", samples)
        )
    return out, notes


def _rescue_or_none(rule: ColumnGuess, why: str, samples: list[str]) -> ColumnGuess:
    if rule.field and rule.confidence >= RULE_RESCUE_CONFIDENCE:
        return ColumnGuess(
            rule.column, rule.field, rule.confidence, f"{why}; {rule.reason}", samples
        )
    return ColumnGuess(rule.column, None, 0.0, f"{why} -- kept as extra data", samples)


def get_column_reader(settings: Settings | None = None) -> ColumnReader:
    s = settings or get_settings()
    if s.column_reader_name() == "llm":
        return LLMColumnReader(s.openrouter_api_key)
    return RuleColumnReader()


def read_columns(
    headers: list[str], rows: list[dict[str, str]], settings: Settings | None = None
) -> ColumnMap:
    return get_column_reader(settings).read(headers, rows)
