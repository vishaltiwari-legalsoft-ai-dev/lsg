"""Decode fetched HTML bytes to text without mangling them.

Found in the live probe: pages decoded with a hard-coded
`bytes.decode("utf-8", errors="replace")` turned Windows-1252 curly apostrophes into
U+FFFD — "You won’t pay anything unless you win" became "You won�t pay…". That text
became evidence quotations and would have reached the UI and the fee patterns.

Order: byte-order mark → the page's own declared charset (<meta charset> or
http-equiv) → strict UTF-8 → Windows-1252 (the usual encoding of the US small-firm sites
that break) → UTF-8 with replacement as the last resort only.
"""

from __future__ import annotations

import codecs
import re

_META_CHARSET = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_\-:.]+)""", re.IGNORECASE
)
_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def _declared_charset(body: bytes) -> str | None:
    match = _META_CHARSET.search(body[:4096])
    if not match:
        return None
    name = match.group(1).decode("ascii", "ignore").strip().lower()
    try:
        return codecs.lookup(name).name
    except LookupError:
        return None


def decode_html(body: bytes | None) -> str:
    if not body:
        return ""
    for bom, encoding in _BOMS:
        if body.startswith(bom):
            return body.decode(encoding, errors="replace")

    candidates: list[str] = []
    declared = _declared_charset(body)
    if declared:
        candidates.append(declared)
    candidates += ["utf-8", "cp1252"]

    for encoding in candidates:
        try:
            return body.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", errors="replace")
