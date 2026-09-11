"""P5 -- JSON-LD (+ microdata) extractor (context/40-pipeline/02-component-register.md P5).

Deterministic schema.org extraction, source `site:jsonld`, confidence 0.95 -- the
highest of any source in this system, because a firm's own structured markup is a
direct first-party claim rather than an inference.

Scope, straight from the task brief:
  * LegalService / Attorney / LocalBusiness / Organization / ProfessionalService
    nodes (including inside @graph) -> canonical_name, phone_e164, address,
    languages, spanish_intake, entity_kind ('private_firm', 0.8, LegalService/
    Attorney only), country ('US' when addressCountry is US/USA/United States).
  * Person/Attorney nodes -> the informational `jsonld_people` list (name + title)
    for the contact resolvers. Never attorney_count -- that is the team page,
    read by the LLM, and nothing else (see the extraction contract).
  * JobPosting nodes are the careers watcher's turf, skipped outright.

One claim per attribute per firm, not per page: most sites repeat the same
site-wide LegalService block on every page, and writing one row per page would
turn firm_attribute into page-count noise rather than a claim. Documents are
walked oldest-fetched-first; the first matching node for a scalar attribute wins
and its evidence/observed_at travel with it. Languages and people are unions
across every page, observed_at = the newest contributing document, per the
"observed_at = the source document's fetched_at (use the newest document the
claim came from)" rule in the task brief.
"""

from __future__ import annotations

import re
from typing import Any

import extruct

from lge.norm import norm_addr, norm_phone
from lge.planes.p._claims import (
    compute_input_hash,
    fetch_documents,
    read_html,
    select_firm_ids,
    write_claim,
)
from lge.registry import RunContext, RunResult, component
from lge.store.objects import ObjectStore, get_store

_VERSION = "p5:v1"
_SOURCE = "site:jsonld"
_CONFIDENCE = 0.95
_ENTITY_KIND_CONFIDENCE = 0.8

_ORG_TYPES = {"legalservice", "attorney", "localbusiness", "organization", "professionalservice"}
_ENTITY_KIND_TYPES = {"legalservice", "attorney"}
_PERSON_TYPES = {"person", "attorney"}
_SKIP_TYPES = {"jobposting"}

_US_COUNTRY_NAMES = {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA", "U.S.", "U.S.A."}

_LANGUAGE_NAME_TO_ISO: dict[str, str] = {
    "english": "en",
    "spanish": "es",
    "español": "es",
    "espanol": "es",
    "french": "fr",
    "français": "fr",
    "chinese": "zh",
    "mandarin": "zh",
    "cantonese": "zh",
    "vietnamese": "vi",
    "korean": "ko",
    "tagalog": "tl",
    "filipino": "tl",
    "russian": "ru",
    "arabic": "ar",
    "portuguese": "pt",
    "polish": "pl",
    "german": "de",
    "italian": "it",
    "japanese": "ja",
    "hindi": "hi",
    "punjabi": "pa",
    "urdu": "ur",
    "haitian creole": "ht",
    "creole": "ht",
    "armenian": "hy",
    "farsi": "fa",
    "persian": "fa",
    "khmer": "km",
    "cambodian": "km",
    "laotian": "lo",
    "lao": "lo",
    "thai": "th",
    "ukrainian": "uk",
    "amharic": "am",
    "somali": "so",
}


@component(
    "p5_jsonld",
    "P",
    "JSON-LD/microdata extractor: schema.org LegalService/Attorney/... -> firm_attribute",
)
def run(ctx: RunContext, *, store: ObjectStore | None = None, **opts: object) -> RunResult:
    store = store or get_store()
    result = RunResult()
    firm_ids = select_firm_ids(
        ctx.conn,
        firm_ids_file=opts.get("firm_ids_file"),  # type: ignore[arg-type]
        limit=opts.get("limit"),  # type: ignore[arg-type]
    )

    for firm_id in firm_ids:
        try:
            docs = fetch_documents(ctx.conn, firm_id, status_200_only=True)
            if not docs:
                result.skipped += 1
                continue

            input_hash = compute_input_hash((d["content_hash"] for d in docs), _VERSION)
            with ctx.once("p5_jsonld", str(firm_id), input_hash) as should_run:
                if not should_run:
                    result.skipped += 1
                    continue
                _process_firm(ctx.conn, firm_id, docs, store)
            result.processed += 1
        except Exception as exc:  # noqa: BLE001 -- per-firm isolation, never global
            result.failed += 1
            result.notes.append(f"p5_jsonld firm={firm_id}: {exc}")

    return result


def _process_firm(conn: Any, firm_id: Any, docs: list[dict], store: ObjectStore) -> None:
    canonical_name: tuple[str, str | None, Any] | None = None
    phone_e164: tuple[str, str | None, Any] | None = None
    address: tuple[dict, str | None, Any] | None = None
    country: tuple[str, str | None, Any] | None = None
    entity_kind: tuple[str, str | None, Any] | None = None
    languages: dict[str, tuple[str, Any]] = {}  # iso code -> (raw token, fetched_at)
    people: dict[tuple[str, str | None], Any] = {}  # (name, title) -> fetched_at

    for doc in docs:
        html = read_html(store, doc["object_key"])
        if not html:
            continue
        fetched_at = doc["fetched_at"]

        for node in _iter_nodes(html):
            types = _type_set(node)
            if types & _SKIP_TYPES:
                continue

            if types & _ORG_TYPES:
                if canonical_name is None:
                    name = _flatten_text(node.get("name") or node.get("legalName"))
                    if name:
                        canonical_name = (name, None, fetched_at)

                if phone_e164 is None:
                    raw_tel = _flatten_text(node.get("telephone"))
                    if raw_tel:
                        e164 = norm_phone(raw_tel)
                        if e164:
                            phone_e164 = (e164, raw_tel, fetched_at)

                addr_raw = _normalize_nested(node.get("address"))
                if addr_raw:
                    if address is None:
                        street = _flatten_text(addr_raw.get("streetAddress"))
                        city = _flatten_text(addr_raw.get("addressLocality"))
                        state = _flatten_text(addr_raw.get("addressRegion"))
                        zip_code = _flatten_text(addr_raw.get("postalCode"))
                        addr = norm_addr(street, city, state, zip_code)
                        if addr.street_norm or addr.zip5:
                            address = (
                                {
                                    "street_norm": addr.street_norm,
                                    "unit": addr.unit,
                                    "city": addr.city,
                                    "state": addr.state,
                                    "zip5": addr.zip5,
                                    "addr_hash": addr.addr_hash,
                                },
                                street,
                                fetched_at,
                            )
                    if country is None:
                        country_text = _flatten_text(addr_raw.get("addressCountry"))
                        if country_text and country_text.strip().upper() in _US_COUNTRY_NAMES:
                            country = ("US", country_text, fetched_at)

                if entity_kind is None and (types & _ENTITY_KIND_TYPES):
                    raw_type = _flatten_text(node.get("@type"))
                    entity_kind = ("private_firm", raw_type, fetched_at)

                for token in _language_tokens(node):
                    code = _lang_to_iso(token)
                    if code and code not in languages:
                        languages[code] = (token, fetched_at)

            if types & _PERSON_TYPES:
                name = _flatten_text(node.get("name"))
                if name:
                    title = _flatten_text(node.get("jobTitle"))
                    key = (name, title)
                    if key not in people:
                        people[key] = fetched_at

    if canonical_name:
        value, evidence, fetched_at = canonical_name
        write_claim(
            conn, firm_id, "canonical_name", value, _SOURCE, _CONFIDENCE, evidence, fetched_at
        )
    if phone_e164:
        value, evidence, fetched_at = phone_e164
        write_claim(
            conn, firm_id, "phone_e164", value, _SOURCE, _CONFIDENCE, evidence, fetched_at
        )
    if address:
        value, evidence, fetched_at = address
        write_claim(conn, firm_id, "address", value, _SOURCE, _CONFIDENCE, evidence, fetched_at)
    if country:
        value, evidence, fetched_at = country
        write_claim(conn, firm_id, "country", value, _SOURCE, _CONFIDENCE, evidence, fetched_at)
    if entity_kind:
        value, evidence, fetched_at = entity_kind
        write_claim(
            conn, firm_id, "entity_kind", value, _SOURCE,
            _ENTITY_KIND_CONFIDENCE, evidence, fetched_at,
        )
    if languages:
        codes = sorted(languages)
        evidence = ", ".join(sorted({tok for tok, _fa in languages.values()}))
        newest = max(fa for _tok, fa in languages.values())
        write_claim(conn, firm_id, "languages", codes, _SOURCE, _CONFIDENCE, evidence, newest)
        if "es" in languages:
            es_token, es_fetched_at = languages["es"]
            write_claim(
                conn, firm_id, "spanish_intake", True, _SOURCE, _CONFIDENCE, es_token, es_fetched_at
            )
    if people:
        value = [{"name": name, "title": title} for (name, title) in people]
        newest = max(people.values())
        write_claim(conn, firm_id, "jsonld_people", value, _SOURCE, _CONFIDENCE, None, newest)


# ---------------------------------------------------------------------------
# JSON-LD / microdata node walking
# ---------------------------------------------------------------------------


def _iter_nodes(html: str):
    """Every JSON-LD node (graph-flattened) and microdata item on the page, each
    normalized to one flat dict keyed by schema.org property name plus "@type"."""
    if not html or not html.strip():
        return
    try:
        data = extruct.extract(html, syntaxes=["json-ld", "microdata"], errors="ignore")
    except Exception:  # noqa: BLE001 -- an unparseable page has no JSON-LD, not a crash
        return
    for item in data.get("json-ld") or []:
        yield from _flatten_jsonld(item)
    for item in data.get("microdata") or []:
        node = _normalize_microdata(item)
        if node is not None:
            yield node


def _flatten_jsonld(item: Any):
    if isinstance(item, list):
        for sub in item:
            yield from _flatten_jsonld(sub)
        return
    if not isinstance(item, dict):
        return
    graph = item.get("@graph")
    if isinstance(graph, list):
        for sub in graph:
            yield from _flatten_jsonld(sub)
        return
    yield item


def _normalize_microdata(item: Any) -> dict | None:
    if not isinstance(item, dict):
        return None
    node = dict(item.get("properties") or {})
    node["@type"] = item.get("type")
    return node


def _normalize_nested(value: Any) -> dict | None:
    """A nested JSON-LD object (already a plain dict) or a nested microdata item
    ({"type": ..., "properties": {...}}) -> one flat dict, or None."""
    if not isinstance(value, dict):
        return None
    if "properties" in value and set(value) <= {"type", "properties", "htmlNode"}:
        out = dict(value.get("properties") or {})
        out["@type"] = value.get("type")
        return out
    return value


def _type_set(node: dict) -> set[str]:
    raw = node.get("@type")
    if raw is None:
        return set()
    values = raw if isinstance(raw, list) else [raw]
    out: set[str] = set()
    for v in values:
        if not isinstance(v, str) or not v.strip():
            continue
        name = v.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        out.add(name.strip().casefold())
    return out


def _flatten_text(value: Any) -> str | None:
    if isinstance(value, str):
        v = value.strip()
        return v or None
    if isinstance(value, dict):
        return _flatten_text(value.get("name") or value.get("@id") or value.get("value"))
    if isinstance(value, list):
        for v in value:
            t = _flatten_text(v)
            if t:
                return t
        return None
    return None


def _flatten_list_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for v in value:
            out.extend(_flatten_list_text(v))
        return out
    t = _flatten_text(value)
    return [t] if t else []


def _language_tokens(node: dict) -> list[str]:
    tokens = _flatten_list_text(node.get("knowsLanguage")) + _flatten_list_text(
        node.get("availableLanguage")
    )
    contact = node.get("contactPoint")
    contacts = contact if isinstance(contact, list) else ([contact] if contact else [])
    for cp in contacts:
        cp_norm = _normalize_nested(cp)
        if cp_norm:
            tokens.extend(_flatten_list_text(cp_norm.get("availableLanguage")))
    return tokens


def _lang_to_iso(token: str) -> str | None:
    t = token.strip()
    if not t:
        return None
    low = t.casefold()
    if low in _LANGUAGE_NAME_TO_ISO:
        return _LANGUAGE_NAME_TO_ISO[low]
    primary = re.split(r"[-_]", t)[0].casefold()
    if len(primary) == 2 and primary.isalpha():
        return primary
    return None
