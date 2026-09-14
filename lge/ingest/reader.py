"""Read a sheet -- CSV in any common encoding and delimiter, or XLSX -- into
headers and rows of strings. Never guesses meaning; that is sniff's job."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
_DELIMITERS = ",;\t|"


@dataclass
class Table:
    headers: list[str]
    rows: list[dict[str, str]]
    format: str  # "csv" | "xlsx"
    encoding: str | None = None
    delimiter: str | None = None
    sheet: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)


def _decode(data: bytes) -> tuple[str, str]:
    for enc in _ENCODINGS:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def _unique_headers(raw: list[object]) -> list[str]:
    """Blank headers become col_N; duplicates get a _2, _3 suffix so no cell is
    silently dropped by a dict."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for i, h in enumerate(raw):
        name = " ".join(str(h).split()) if h is not None and str(h).strip() else f"col_{i + 1}"
        n = seen.get(name, 0) + 1
        seen[name] = n
        out.append(name if n == 1 else f"{name}_{n}")
    return out


def _read_csv(data: bytes) -> Table:
    text, encoding = _decode(data)
    sample = text[:20000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=_DELIMITERS)
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    raw_rows = [r for r in reader]
    # skip leading blank lines
    while raw_rows and not any(c.strip() for c in raw_rows[0]):
        raw_rows.pop(0)
    if not raw_rows:
        return Table([], [], "csv", encoding, delimiter, notes=["empty file"])
    headers = _unique_headers(raw_rows[0])
    rows: list[dict[str, str]] = []
    for r in raw_rows[1:]:
        if not any(c.strip() for c in r):
            continue
        cells = [c.strip() for c in r] + [""] * (len(headers) - len(r))
        rows.append(dict(zip(headers, cells[: len(headers)], strict=False)))
    return Table(headers, rows, "csv", encoding, delimiter)


def _read_xlsx(data: bytes) -> Table:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    notes = [f"{len(wb.worksheets)} sheet(s); read '{ws.title}'"] if len(wb.worksheets) > 1 else []
    it = ws.iter_rows(values_only=True)
    header_row: tuple | None = None
    for r in it:
        if r and any(c is not None and str(c).strip() for c in r):
            header_row = r
            break
    if header_row is None:
        return Table([], [], "xlsx", sheet=ws.title, notes=["empty sheet"])
    headers = _unique_headers(list(header_row))
    rows: list[dict[str, str]] = []
    for r in it:
        if not r or not any(c is not None and str(c).strip() for c in r):
            continue
        cells = ["" if c is None else str(c).strip() for c in r]
        cells += [""] * (len(headers) - len(cells))
        rows.append(dict(zip(headers, cells[: len(headers)], strict=False)))
    return Table(headers, rows, "xlsx", sheet=ws.title, notes=notes)


def read_table(path: str | Path) -> Table:
    p = Path(path)
    data = p.read_bytes()
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        return _read_xlsx(data)
    if data[:4] == b"PK\x03\x04":  # an xlsx with the wrong extension
        return _read_xlsx(data)
    return _read_csv(data)
