"""classify_role — owner / admin / attorney / unknown from a raw job title.

Bump the caller's stored role norm/version whenever this output can change for any
input. See context/10-icp/07-decision-makers-and-lead-record.md: capturing the
owner AND the administrator (never just one) is what makes a collected lead usable.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "contact_roles.yml"

# Evaluation order matters: owner and owner_weak must be checked before admin/
# attorney so e.g. "Managing Attorney" resolves to owner, and "Attorney/Partner"
# (caught only by owner_weak's combined pattern) resolves to owner before the bare
# "attorney" pattern in the attorney bucket ever gets a chance to match it.
_BUCKET_ORDER: tuple[tuple[str, str], ...] = (
    ("owner", "owner"),
    ("owner_weak", "owner"),
    ("admin", "admin"),
    ("attorney", "attorney"),
)


@dataclass(frozen=True, slots=True)
class RoleResult:
    role: str  # owner | admin | attorney | unknown
    confidence: float


@functools.lru_cache(maxsize=1)
def _load_config() -> dict:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@functools.lru_cache(maxsize=1)
def _compiled_buckets() -> dict[str, tuple[float, tuple[re.Pattern[str], ...]]]:
    cfg = _load_config()
    out: dict[str, tuple[float, tuple[re.Pattern[str], ...]]] = {}
    for bucket_name, _role in _BUCKET_ORDER:
        bucket = cfg[bucket_name]
        out[bucket_name] = (
            float(bucket["confidence"]),
            tuple(re.compile(p, re.IGNORECASE) for p in bucket["patterns"]),
        )
    return out


def classify_role(title: str | None) -> RoleResult:
    if not title or not title.strip():
        return RoleResult("unknown", 0.0)
    text = title.strip()
    buckets = _compiled_buckets()
    for bucket_name, role in _BUCKET_ORDER:
        confidence, patterns = buckets[bucket_name]
        if any(p.search(text) for p in patterns):
            return RoleResult(role, confidence)
    return RoleResult("unknown", 0.0)
