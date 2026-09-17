"""Read a sheet -- CSV in any common encoding and delimiter, or XLSX -- into
headers and rows of strings. Never guesses meaning; that is the column
reader's job.

Rows stream. `read_head` gives the column reader its sample, `count_rows`
plans the batches, and `iter_batches` hands the loader one batch at a time
without ever holding the whole sheet: a 100,000-row sheet costs the same per
row as a 100-row one. `read_table` still materialises everything, for small
sheets and tests.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lge.ingest.batches import Batch

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


@dataclass
class Source:
    """An opened sheet: its shape, and a fresh row generator each time
    `rows()` is called. Blank rows are skipped, short rows padded, long rows
    truncated to the headers -- the same row a `Table` would hold."""

    headers: list[str]
    format: str
    encoding: str | None = None
    delimiter: str | None = None
    sheet: str | None = None
    notes: list[str] = field(default_factory=list)
    _rows: object = None  # a zero-argument callable returning an iterator of raw cell lists

    def rows(self) -> Iterator[dict[str, str]]:
        if self._rows is None:
            return iter(())
        return _to_dicts(self.headers, self._rows())  # type: ignore[operator]


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


def _blank(cells: Sequence[object]) -> bool:
    return not any(c is not None and str(c).strip() for c in cells)


def _to_dicts(headers: list[str], raw_rows: Iterator[Sequence[object]]) -> Iterator[dict[str, str]]:
    width = len(headers)
    for r in raw_rows:
        if not r or _blank(r):
            continue
        cells = ["" if c is None else str(c).strip() for c in r]
        cells += [""] * (width - len(cells))
        yield dict(zip(headers, cells[:width], strict=False))


def _open_csv(data: bytes) -> Source:
    text, encoding = _decode(data)
    sample = text[:20000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=_DELIMITERS)
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","

    def raw() -> Iterator[list[str]]:
        return csv.reader(io.StringIO(text), delimiter=delimiter)

    # the header is the first non-blank line; data starts after it
    header_row: list[str] | None = None
    skip = 0
    for r in raw():
        skip += 1
        if r and not _blank(r):
            header_row = r
            break
    if header_row is None:
        return Source([], "csv", encoding, delimiter, notes=["empty file"])
    headers = _unique_headers(list(header_row))

    def data_rows() -> Iterator[list[str]]:
        return islice(raw(), skip, None)

    return Source(headers, "csv", encoding, delimiter, _rows=data_rows)


def _open_xlsx(data: bytes) -> Source:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    notes = [f"{len(wb.worksheets)} sheet(s); read '{ws.title}'"] if len(wb.worksheets) > 1 else []
    header_row: tuple | None = None
    skip = 0
    for r in ws.iter_rows(values_only=True):
        skip += 1
        if r and not _blank(r):
            header_row = r
            break
    if header_row is None:
        wb.close()
        return Source([], "xlsx", sheet=ws.title, notes=["empty sheet"])
    headers = _unique_headers(list(header_row))

    def data_rows() -> Iterator[tuple]:
        # a fresh workbook per pass: openpyxl's read-only sheet is a single
        # forward stream, and the bytes are already in memory
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            yield from islice(book.worksheets[0].iter_rows(values_only=True), skip, None)
        finally:
            book.close()

    wb.close()
    return Source(headers, "xlsx", sheet=ws.title, notes=notes, _rows=data_rows)


def open_sheet(path: str | Path) -> Source:
    p = Path(path)
    data = p.read_bytes()
    if p.suffix.lower() in (".xlsx", ".xlsm") or data[:4] == b"PK\x03\x04":
        return _open_xlsx(data)  # (an xlsx with the wrong extension still opens)
    return _open_csv(data)


def _table(src: Source, rows: list[dict[str, str]]) -> Table:
    return Table(src.headers, rows, src.format, src.encoding, src.delimiter, src.sheet,
                 list(src.notes))


def read_table(path: str | Path) -> Table:
    """The whole sheet in memory. For small sheets and tests; the loader streams."""
    src = open_sheet(path)
    return _table(src, list(src.rows()))


def read_head(path: str | Path, n: int) -> Table:
    """Headers and the first `n` data rows -- the column reader's sample."""
    src = open_sheet(path)
    return _table(src, list(islice(src.rows(), n)))


def count_rows(path: str | Path) -> int:
    """Non-blank data rows, counted in one streaming pass."""
    return sum(1 for _ in open_sheet(path).rows())


def iter_rows(path: str | Path) -> Iterator[dict[str, str]]:
    return open_sheet(path).rows()


def iter_batches(
    path: str | Path, batches: Sequence[Batch]
) -> Iterator[tuple[Batch, list[dict[str, str]]]]:
    """Walk the sheet once and yield each planned batch with its rows, in
    order. Batches are contiguous 1-based row ranges (lge.ingest.batches);
    a batch past the end of the sheet yields the rows that exist."""
    planned = sorted(batches, key=lambda b: b.row_start)
    if not planned:
        return
    rows = open_sheet(path).rows()
    row_no = 0
    for batch in planned:
        while row_no < batch.row_start - 1:  # rows before this batch (a gap in the plan)
            if next(rows, None) is None:
                return
            row_no += 1
        chunk: list[dict[str, str]] = []
        while row_no < batch.row_end:
            r = next(rows, None)
            if r is None:
                break
            row_no += 1
            chunk.append(r)
        yield batch, chunk
        if row_no < batch.row_end:  # the sheet ended inside this batch
            return
