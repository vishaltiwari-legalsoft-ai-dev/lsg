"""Pure, deterministic, versioned normalizers.

Applied at write time, never at query time — a normalizer run inside a WHERE clause
defeats the trigram and uniqueness indexes it exists to feed. See
context/30-data-model/02-normalization-contracts.md.

NORM_VERSION is stored alongside every canonical value it produces. When a
normalizer's output can change for any input, bump its entry here so affected rows
can be identified and recomputed from stored raw HTML without a re-crawl.
"""

from __future__ import annotations

from lge.norm.addr import AddrNorm, norm_addr
from lge.norm.domain import (
    FREEMAIL_BLOCKLIST,
    SHARED_HOST_BLOCKLIST,
    norm_domain,
    norm_email_domain,
)
from lge.norm.name import norm_name
from lge.norm.phone import norm_phone, shared_numbers
from lge.norm.practice import PracticeResult, map_practice_label, norm_practice

NORM_VERSION: dict[str, str] = {
    "norm_domain": "1",
    "norm_phone": "1",
    "norm_addr": "1",
    "norm_name": "1",
    "norm_practice": "2",  # v2: service phrases, not bare will/trust/visa/roundup
}

__all__ = [
    "NORM_VERSION",
    "AddrNorm",
    "FREEMAIL_BLOCKLIST",
    "PracticeResult",
    "SHARED_HOST_BLOCKLIST",
    "map_practice_label",
    "norm_addr",
    "norm_domain",
    "norm_email_domain",
    "norm_name",
    "norm_phone",
    "norm_practice",
    "shared_numbers",
]
