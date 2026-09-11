"""Content-addressed object store for raw fetched bytes (component P2).

The spec stores raw HTML in GCS; locally it is a directory. Storing the raw HTML,
always, is the single reason a later schema, prompt or normalizer change becomes a
re-parse instead of a re-crawl. Keys are the sha256 of the raw bytes, so the same
page fetched twice is stored once and `key` doubles as the document content hash.
"""

from __future__ import annotations

import gzip
import hashlib
from functools import lru_cache
from pathlib import Path

from lge.settings import get_settings


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.gz"

    def put(self, data: bytes) -> str:
        """Store bytes; return their key (sha256 hex). Idempotent."""
        key = content_hash(data)
        path = self._path(key)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(gzip.compress(data))
            tmp.replace(path)
        return key

    def get(self, key: str) -> bytes:
        return gzip.decompress(self._path(key).read_bytes())

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


@lru_cache(maxsize=1)
def get_store() -> ObjectStore:
    return ObjectStore(get_settings().object_store)
