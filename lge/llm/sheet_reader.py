"""The AI reads a sheet's columns (D-042): the header row and a dozen sample
rows go to the model once, with the field vocabulary, and it answers which
column is which, how sure it is, why, and what the sheet lacks that matters.
One call per sheet -- a few thousand tokens, a fraction of a cent.

What comes back is a *proposal*. `lge.ingest.columns` checks every typed
field against the values (an "email" column whose cells are not emails is
not an email column) before it becomes the column map. This module only
talks to the model.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from lge.ingest.vocab import FIELDS
from lge.llm.client import LLMCallError, call_openrouter
from lge.llm.schema import response_format_for
from lge.llm.sync import run_blocking

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "llm.yml"
_CELL_CHARS = 60
_HEADER_CHARS = 80


class ColumnRead(BaseModel):
    """One column, as the model read it. `field` is a vocabulary name or
    null for "this column is none of them"."""

    model_config = ConfigDict(extra="forbid")

    column: str
    field: str | None
    confidence: float
    reason: str


class SheetRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[ColumnRead]
    notes: list[str]


_RESPONSE_FORMAT = response_format_for(SheetRead, "sheet_read")


class SheetReadError(Exception):
    """The model could not be asked, or did not answer in the schema."""


@functools.lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    reader = dict(cfg.get("sheet_reader") or {})
    request = dict(cfg.get("request") or {})
    return {
        "model": reader.get("model", "anthropic/claude-haiku-4.5"),
        "sample_rows": int(reader.get("sample_rows", 12)),
        "max_output_tokens": int(reader.get("max_output_tokens", 1500)),
        "timeout_s": float(reader.get("timeout_s", 60)),
        "max_retries": int(request.get("max_retries", 3)),
        "backoff_base_s": float(request.get("backoff_base_s", 1.0)),
        "backoff_max_s": float(request.get("backoff_max_s", 30.0)),
        "referer": cfg.get("referer", "https://legalsoft.com"),
        "title": cfg.get("title", "Legal Soft Lead Engine"),
    }


def _vocabulary_lines() -> str:
    lines = []
    for f in FIELDS:
        hint = f.description or ""
        also = ", ".join(f.synonyms[:4])
        lines.append(f"- {f.name} ({f.label}): {hint} e.g. headers like: {also}".rstrip())
    return "\n".join(lines)


SYSTEM_PROMPT = f"""You read the header row and a few sample rows of a spreadsheet of law firms \
and say which column carries which field from a fixed vocabulary.

The vocabulary (use these names exactly, or null):
{_vocabulary_lines()}

Rules:
- Every header in the input appears exactly once in `columns`, in the same order.
- A column maps to one field or to null. Null means "none of these" -- prefer null over a \
guess you would put under 0.5.
- Columns about the firm (its name, site, city, size) never become contact fields \
(person_name, person_title, email, phone, linkedin), and the reverse. A "Name" beside "Job \
Title" and "Email" is a person; a "Name" beside "Website" and "Employees" is the firm.
- `firm_type` is any industry, practice-area or description column. `firm_size` is any \
headcount or attorney-count column. `contacted_before` is a yes/no or status of past outreach; \
`contacted_at` is its date.
- Judge by the values as much as the header: a header that says "Website" over email \
addresses is an email column.
- `confidence` is 0 to 1. `reason` is at most twelve words.
- `notes`: up to five short plain-words remarks on what the sheet lacks or what looks odd \
(for example "no website column; only an email column" or "size column is a text range"). \
Do not restate the mapping in the notes.
"""


def _trim(s: str, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def build_user_message(headers: list[str], sample_rows: list[dict[str, str]], limit: int) -> str:
    rows = [[_trim(r.get(h, ""), _CELL_CHARS) for h in headers] for r in sample_rows[:limit]]
    payload = {"headers": [_trim(h, _HEADER_CHARS) for h in headers], "sample_rows": rows}
    return json.dumps(payload, ensure_ascii=False)


async def read_sheet_async(
    headers: list[str],
    sample_rows: list[dict[str, str]],
    *,
    api_key: str,
    http_client: httpx.AsyncClient | None = None,
) -> SheetRead:
    if not api_key:
        raise SheetReadError("no OpenRouter key")
    cfg = load_config()
    own_client = http_client is None
    client = http_client or httpx.AsyncClient()
    try:
        try:
            resp = await call_openrouter(
                client,
                api_key=api_key,
                model=cfg["model"],
                system=SYSTEM_PROMPT,
                user=build_user_message(headers, sample_rows, cfg["sample_rows"]),
                response_format=_RESPONSE_FORMAT,
                max_tokens=cfg["max_output_tokens"],
                timeout_s=cfg["timeout_s"],
                max_retries=cfg["max_retries"],
                backoff_base_s=cfg["backoff_base_s"],
                backoff_max_s=cfg["backoff_max_s"],
                referer=cfg["referer"],
                title=cfg["title"],
            )
        except LLMCallError as exc:
            raise SheetReadError(str(exc)) from exc
        try:
            return SheetRead.model_validate_json(resp.content)
        except ValidationError as exc:
            raise SheetReadError(f"answer did not match the schema: {exc}") from exc
    finally:
        if own_client:
            await client.aclose()


def read_sheet(headers: list[str], sample_rows: list[dict[str, str]], *, api_key: str) -> SheetRead:
    """Blocking form for the loader and the CLI."""
    return run_blocking(lambda: read_sheet_async(headers, sample_rows, api_key=api_key))
