"""What Legal Soft offers, said once per email, and the one thing the email
asks for (D-070).

The copy files carry the conversation; this module adds two short blocks
under it, above the signature:

  * the offer -- one paragraph of Legal Soft's own numbers (config/usp.yml),
    chosen by the pain that armed the lead, rotated across the nine emails,
    and never repeating what the email's own words already say;
  * the call to action -- a label and a link (config/sender.yml `cta`), with
    a line for the reader who would rather reply.

Pure functions of the config and the email's text; nothing here reads the
store or calls a model. Every number is the company's published claim.
"""

from __future__ import annotations

import functools
import html
from pathlib import Path
from typing import Any

import yaml

from lge.journey.render import load_sender

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
USP_CONFIG = _PROJECT_ROOT / "config" / "usp.yml"


@functools.cache
def load_usp(path: Path = USP_CONFIG) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _people(cfg: dict[str, Any], pain: str | None, tier: str | None) -> str:
    people = cfg.get("people") or {}
    entry = people.get(pain or "default", people.get("default", "legal staff"))
    if isinstance(entry, dict):
        return str(entry.get(tier or "", entry.get("default", "legal staff")))
    return str(entry)


def _said_already(fact: dict[str, Any], text: str) -> bool:
    # The copy files are hard-wrapped: "under three\ndays" is "three days".
    low = " ".join(text.lower().split())
    return any(str(w).lower() in low for w in fact.get("covers") or [])


def pick_facts(step: int, body: str, cfg: dict[str, Any] | None = None) -> list[str]:
    """The facts this email leads with: the touch's own order, skipping what
    the email already says, `max_facts` at most."""
    cfg = cfg if cfg is not None else load_usp()
    facts = cfg.get("facts") or {}
    order = (cfg.get("by_touch") or {}).get(step) or list(facts)
    limit = int(cfg.get("max_facts", 3))
    fresh = [k for k in order if k in facts and not _said_already(facts[k], body)]
    picked = fresh[:limit]
    # Every email carries a number: if none of the facts chosen has one, the
    # last gives way to the first fact with a figure the email has not used.
    def has_number(key: str) -> bool:
        return any(ch.isdigit() for ch in str(facts[key]["text"]))

    if picked and not any(has_number(k) for k in picked):
        numeric = next(
            (k for k in [*fresh, *facts] if k not in picked and has_number(k)
             and not _said_already(facts[k], body)),
            None,
        )
        if numeric is not None:
            picked = [*picked[: limit - 1], numeric]
    return picked


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return f"{', '.join(parts[:-1])}, and {parts[-1]}"


def usp_paragraph(
    step: int, body: str, *, pain: str | None, tier: str | None,
    cfg: dict[str, Any] | None = None,
) -> str:
    """The offer paragraph for one email, or "" when the config is off or
    the email already says everything this touch would add."""
    cfg = cfg if cfg is not None else load_usp()
    if not cfg.get("enabled", True):
        return ""
    facts = cfg.get("facts") or {}
    keys = pick_facts(step, body, cfg)
    if not keys:
        return ""
    verbs = [str(facts[k]["text"]) for k in keys if facts[k].get("form") == "verb"]
    clauses = [str(facts[k]["text"]) for k in keys if facts[k].get("form") != "verb"]
    sentences: list[str] = []
    if verbs:
        sentences.append(f"Legal Soft's {_people(cfg, pain, tier)} {_join(verbs)}.")
    sentences.extend(c if c.endswith(".") else f"{c}." for c in clauses)
    answers = cfg.get("answers") or {}
    answer = answers.get(pain or "default", answers.get("default"))
    # The answer to the pain goes once, with the first email that names it.
    if answer and step in (1, 2):
        sentences.append(str(answer))
    return " ".join(sentences)


def cta_block(cfg: dict[str, Any] | None = None) -> str:
    """The call to action as plain text: the label and the link on one line,
    the reply line under it. "" when no link is configured -- a call to
    action with nowhere to go is not drafted."""
    cta = (cfg if cfg is not None else load_sender()).get("cta") or {}
    label = (cta.get("label") or "").strip()
    url = (cta.get("url") or "").strip()
    if not label or not url:
        return ""
    reply = (cta.get("reply") or "").strip()
    return f"{label}: {url}" + (f"\n{reply}" if reply else "")


def cta_html(cfg: dict[str, Any] | None = None) -> str:
    """The same call to action as a button, for a sending tool that writes
    HTML. Inline styles only: mail clients drop style sheets."""
    cta = (cfg if cfg is not None else load_sender()).get("cta") or {}
    label = (cta.get("label") or "").strip()
    url = (cta.get("url") or "").strip()
    if not label or not url:
        return ""
    return (
        f'<a href="{html.escape(url, quote=True)}" '
        'style="display:inline-block;padding:10px 18px;background:#0b3d91;color:#ffffff;'
        'text-decoration:none;border-radius:6px;font-weight:600;font-family:Arial,sans-serif">'
        f"{html.escape(label)}</a>"
    )


def cta_missing(cfg: dict[str, Any] | None = None) -> list[str]:
    cta = (cfg if cfg is not None else load_sender()).get("cta") or {}
    return [] if (cta.get("url") or "").strip() else ["a link for the call to action"]
