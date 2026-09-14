"""Rows -> numbered batches. A 37,000-row sheet is not processed in one go:
one bad row or one dropped connection would lose all of it, and a person
cannot review a single 37,000-row result. Batches are contiguous row ranges
(1-based, inclusive) so a batch number always means the same rows."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_BATCH_SIZE = 500
MIN_BATCH_SIZE = 50
MAX_BATCH_SIZE = 5000


@dataclass(frozen=True)
class Batch:
    number: int  # 1-based
    row_start: int  # 1-based, inclusive
    row_end: int  # inclusive

    @property
    def size(self) -> int:
        return self.row_end - self.row_start + 1


def plan_batches(row_count: int, batch_size: int = DEFAULT_BATCH_SIZE) -> list[Batch]:
    size = max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, int(batch_size)))
    out: list[Batch] = []
    start = 1
    number = 1
    while start <= row_count:
        end = min(start + size - 1, row_count)
        out.append(Batch(number, start, end))
        start = end + 1
        number += 1
    return out


def slice_rows(rows: list, batch: Batch) -> list:
    return rows[batch.row_start - 1 : batch.row_end]
