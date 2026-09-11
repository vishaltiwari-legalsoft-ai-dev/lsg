"""Copy-file loading and `{token}` substitution. `journey/copy/*.md` files
are transcribed verbatim from plan/email-drafts.md -- this module's only job
is splitting `Subject: ...` from the body and substituting tokens, never
rewriting prose.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
COPY_ROOT = _PROJECT_ROOT / "journey" / "copy"

_TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_SUBJECT_PREFIX = "Subject:"


def parse_template(text: str) -> tuple[str | None, str]:
    """Split a copy file into (subject, body).

    A full touch file's first line is `Subject: ...`; a "slot fill" partial
    (a middle paragraph swapped in by tier) carries no subject line at all,
    and this returns (None, whole-text-stripped) for those.
    """
    lines = text.splitlines()
    if lines and lines[0].startswith(_SUBJECT_PREFIX):
        subject = lines[0][len(_SUBJECT_PREFIX) :].strip()
        body = "\n".join(lines[1:]).strip("\n")
        return subject, body
    return None, text.strip("\n")


@functools.cache
def _read(rel_path: str) -> str:
    path = COPY_ROOT / rel_path
    return path.read_text(encoding="utf-8")


def load_template(rel_path: str) -> tuple[str | None, str]:
    """Load and split a copy file by its path relative to journey/copy/."""
    return parse_template(_read(rel_path))


def substitute(
    text: str,
    tokens: Mapping[str, str | None],
    fallbacks: Mapping[str, str] | None = None,
) -> tuple[str, list[str]]:
    """Replace every `{name}` in `text`. Resolution order per token:
    1. `tokens[name]` if present and not None
    2. `fallbacks[name]` if given
    3. otherwise the name is recorded as missing and the placeholder is left
       untouched (the caller decides what an unresolved token means).

    Returns (rendered_text, missing_token_names) in first-occurrence order.
    """
    fallbacks = fallbacks or {}
    missing: list[str] = []

    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        value = tokens.get(name)
        if value is not None:
            return str(value)
        if name in fallbacks:
            return fallbacks[name]
        missing.append(name)
        return m.group(0)

    rendered = _TOKEN_RE.sub(repl, text)
    return rendered, missing
