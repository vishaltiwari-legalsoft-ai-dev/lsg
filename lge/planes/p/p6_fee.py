"""P6 -- fee-model detector (context/10-icp/03-fee-model.md, component-register P6).

Pure regex over stored page text (`lge.classify.fee.detect_fee_model` does the actual
precedence/real-estate resolution -- this module's only job is picking the pages,
building the text each one is read as, and writing exactly one `fee_model` claim
per firm.

v2 reads the page's FULL visible text -- title, meta description, header, nav,
footer and body -- from the stored HTML, not P4's main text. Found in the live
probe: 8 of 57 unclassified personal-injury firms said "No fees unless we win" only
in the site header or footer, which the main-text extractor drops on purpose as
boilerplate. A fee promise is exactly what a firm puts in its chrome (D-026). P4's
main text is the fallback when the raw HTML is not in the store.

`unknown` is written like any other value (0.0 confidence, no evidence) -- per
context/40-pipeline/03-extraction-contract.md, a silent non-write here would be
indistinguishable from "P6 hasn't run yet" at reconciliation time. It must be
reachable, not absent.
"""

from __future__ import annotations

from pathlib import Path

import lxml.html
from lxml import etree

from lge.classify.fee import detect_fee_model
from lge.planes.p._claims import (
    compute_input_hash,
    config_fingerprint,
    fetch_documents_with_text,
    read_html,
    select_firm_ids,
    write_claim,
)
from lge.registry import RunContext, RunResult, component
from lge.store.objects import ObjectStore, get_store

_VERSION = "p6:v3"  # v2: the whole visible page, not only P4's main text; v3: negation
# contact / attorneys / team added after the live probe: "No fee unless we win" often
# sits on the contact page. careers stays out (job ads use "fee" in other senses).
_PAGE_KINDS = ("practice", "fees", "home", "about", "other", "contact", "attorneys", "team")
_SOURCE = "regex:p6"
# Mirrors lge/classify/fee.py's own _CONFIG_PATH -- computed independently rather
# than importing that module's private constant, so an edit to fee_patterns.yml
# (owned by lge.classify.fee, not this module) still busts our idempotency key.
_FEE_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "fee_patterns.yml"

# Elements that start a new line of visible text. One line per block is what lets
# the detector quote "No fees unless we win!" from a nav bar as its own sentence
# instead of a run-on of the whole menu.
_BLOCK_TAGS = (
    "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "td", "th",
    "section", "article", "header", "footer", "nav", "aside", "main", "ul", "ol",
    "table", "blockquote", "dd", "dt", "title", "figcaption", "summary",
)
_INVISIBLE_XPATH = "//script|//style|//noscript|//template|//svg"


def page_text(html: str) -> str:
    """Everything a visitor can read on the page, one line per block: the title,
    the meta description, then header, nav, body and footer in document order.
    Scripts, styles and SVG are dropped. Empty string for empty or unparseable HTML."""
    if not html or not html.strip():
        return ""
    try:
        tree = lxml.html.fromstring(html)
    except (etree.ParserError, ValueError):
        return ""
    for el in tree.xpath(_INVISIBLE_XPATH):
        el.drop_tree()
    # Blocks start a new line; inline elements (a, span, strong) get a space so
    # adjacent nav links do not fuse into one word ("HomeAboutNo fees...").
    for el in tree.iter():
        if not isinstance(el.tag, str):
            continue  # comments and processing instructions
        sep = "\n" if el.tag in _BLOCK_TAGS else " "
        el.text = sep + (el.text or "")
        el.tail = sep + (el.tail or "")
    meta = tree.xpath("string(//meta[@name='description']/@content)")
    raw = f"{meta}\n{tree.text_content()}"
    lines = (" ".join(line.split()) for line in raw.split("\n"))
    return "\n".join(line for line in lines if line)


@component("p6_fee", "P", "Fee-model detector: regex over page text, precedence-ordered")
def run(ctx: RunContext, *, store: ObjectStore | None = None, **opts: object) -> RunResult:
    result = RunResult()
    store = store or get_store()
    firm_ids = select_firm_ids(
        ctx.conn,
        firm_ids_file=opts.get("firm_ids_file"),  # type: ignore[arg-type]
        limit=opts.get("limit"),  # type: ignore[arg-type]
    )
    version = f"{_VERSION}:{config_fingerprint(_FEE_CONFIG_PATH)}"

    for firm_id in firm_ids:
        try:
            rows = fetch_documents_with_text(ctx.conn, firm_id, page_kinds=_PAGE_KINDS)
            if not rows:
                result.skipped += 1
                continue

            input_hash = compute_input_hash((r["content_hash"] for r in rows), version)
            with ctx.once("p6_fee", str(firm_id), input_hash) as should_run:
                if not should_run:
                    result.skipped += 1
                    continue

                # Weight stays P4's word count -- the page's own content size, the
                # "page real estate" the spec resolves conflicts by. The chrome is
                # the same on every page, so it must not inflate any one of them.
                sections = []
                for r in rows:
                    text = page_text(read_html(store, r["object_key"])) or (r["main_text"] or "")
                    sections.append((text, float(r["word_count"] or 0)))
                fee = detect_fee_model(sections)
                observed_at = max(r["fetched_at"] for r in rows)

                write_claim(
                    ctx.conn,
                    firm_id,
                    "fee_model",
                    fee.value,
                    _SOURCE,
                    fee.confidence,
                    fee.evidence,
                    observed_at,
                )
            result.processed += 1
        except Exception as exc:  # noqa: BLE001 -- per-firm isolation, never global
            result.failed += 1
            result.notes.append(f"p6_fee firm={firm_id}: {exc}")

    return result
