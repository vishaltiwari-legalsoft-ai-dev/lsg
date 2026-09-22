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


# ---------------------------------------------------------------------------
# Who signs, and the lines the law asks for (D-060)
# ---------------------------------------------------------------------------

SENDER_CONFIG = _PROJECT_ROOT / "config" / "sender.yml"


@functools.cache
def load_sender(path: Path = SENDER_CONFIG) -> dict:
    import yaml

    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def sender_missing(cfg: dict | None = None) -> list[str]:
    """What a person still has to fill in before any of this can be sent, in
    plain words. An email with nobody's name on it reads as a circular, and US
    law wants a postal address and a way to stop."""
    cfg = cfg if cfg is not None else load_sender()
    who = cfg.get("from") or {}
    footer = cfg.get("footer") or {}
    missing = []
    if not (who.get("name") or "").strip():
        missing.append("who signs the emails")
    if not (who.get("reply_to") or "").strip():
        missing.append("the address replies go to")
    if not (footer.get("postal_address") or "").strip():
        missing.append("a postal address, which US law requires")
    if not (footer.get("opt_out") or "").strip():
        missing.append("a line telling people how to stop")
    return missing


def signature(cfg: dict | None = None) -> str:
    """The block appended to every drafted email: who wrote it, for whom, and
    how to make it stop. Whatever is not configured is left out rather than
    invented -- a blank where a postal address should be is visible, and
    `sender_missing` names it."""
    cfg = cfg if cfg is not None else load_sender()
    who = cfg.get("from") or {}
    footer = cfg.get("footer") or {}

    name = (who.get("name") or "").strip()
    title = (who.get("title") or "").strip()
    company = (who.get("company") or "").strip()
    website = (who.get("website") or "").strip()
    reply_to = (who.get("reply_to") or "").strip()

    sign_off = (who.get("sign_off") or "").strip()

    lines: list[str] = []
    if sign_off:
        lines.append(sign_off)
    if name:
        lines.append(f"{name}, {title}" if title else name)
    if company:
        lines.append(f"{company} — {website}" if website else company)
    elif website:
        lines.append(website)
    if reply_to:
        lines.append(reply_to)

    tail = [part for part in (
        (footer.get("postal_address") or "").strip(),
        (footer.get("opt_out") or "").strip(),
    ) if part]
    if tail:
        # The legal footer sits under a rule, the way a business email carries it.
        lines.extend(["", "--"])
        lines.extend(tail)
    return "\n".join(lines)
