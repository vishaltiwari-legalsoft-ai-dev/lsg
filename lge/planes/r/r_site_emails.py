"""r_site_emails -- the email addresses a firm prints on its own pages (Plane R).

Found in the live probe (15 Sep 2026): 100 of 157 reached firms print an address
on their site, 52 of them a personal one (michelle@dressielaw.com,
dfried@friedbonder.com), and none of it was captured -- the only emails on file
were the purchased list's. This component reads the STORED HTML (never
re-fetches) and:

  * attaches a personal address to the one contact at the firm whose name
    renders to that local part under R3's patterns (first.last, flast, first,
    firstl, last). An ambiguous local part (two contacts match) or one that
    matches nobody is never guessed onto a person;
  * records a general inbox (info@, contact@, intake@, office@ ...) as the
    `general_email` claim and a hiring inbox (careers@, hiring@, jobs@, hr@) as
    `hiring_email` -- on the firm record, not on a person;
  * records every address on the firm's domain as `site_emails` (provenance).

Only the firm's own domain counts: a freemail or third-party address on a page
is not the firm's. Read from mailto: links, visible text and "[at]" / "(at)"
spelling. Cloudflare's data-cfemail encoding is deliberately NOT decoded -- it
is an anti-harvesting measure, and the standing rule is never to defeat one.

Rows: contact_email with status 'unverified' (R4 verifies, never this
component) and `pattern` set to the matched pattern; claims under source
'site:page'. Idempotent per firm on the documents read and the contacts on
file, so a new contact from a later AI pass re-runs the attach step.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import re
from typing import Any

from lge.planes.p._claims import (
    compute_input_hash,
    fetch_documents,
    read_html,
    select_firm_ids,
    write_claim,
)
from lge.planes.r.r3_email_pattern import infer_pattern
from lge.registry import RunContext, RunResult, component
from lge.store.objects import ObjectStore, get_store

_COMPONENT_NAME = "r_site_emails"
_VERSION = "r_site_emails:v1"
_SOURCE = "site:page"

_MAILTO_RE = re.compile(r"""href\s*=\s*["']\s*mailto:([^"'?\s>]+)""", re.I)
_EMAIL_RE = re.compile(r"[A-Za-z0-9][\w.+-]*@(?:[\w-]+\.)+[A-Za-z]{2,}")
# "jane [at] firm [dot] com", "jane (at) firm.com"
_OBFUSCATED_RE = re.compile(
    r"([A-Za-z0-9][\w.+-]*)\s*[\[({]\s*at\s*[\])}]\s*"
    r"([\w-]+(?:\s*(?:\.|[\[({]\s*dot\s*[\])}])\s*[\w-]+)+)",
    re.I,
)
_DOT_RE = re.compile(r"\s*[\[({]\s*dot\s*[\])}]\s*|\s*\.\s*", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_FILE_LIKE_RE = re.compile(r"\.(?:png|jpe?g|gif|svg|webp|js|css|pdf)$", re.I)

_GENERAL_LOCALS: tuple[str, ...] = (
    "info", "contact", "office", "intake", "admin", "hello", "mail", "help", "support",
    "reception", "frontdesk", "inquiries", "inquiry", "consult", "consultation",
    "newclient", "newclients", "clients", "cases", "legal", "law", "lawfirm", "firm",
    "team", "staff", "questions", "general", "attorney", "attorneys", "lawyer", "lawyers",
)
_HIRING_LOCALS: tuple[str, ...] = (
    "careers", "career", "hiring", "jobs", "job", "hr", "recruiting", "recruiter",
    "resumes", "resume", "employment", "apply", "talent",
)
_NOT_A_PERSON: frozenset[str] = frozenset(
    _GENERAL_LOCALS + _HIRING_LOCALS + ("webmaster", "marketing", "media", "press", "billing",
                                       "accounting", "noreply", "no-reply", "notifications")
)


def _on_domain(email: str, domain: str) -> bool:
    host = email.rsplit("@", 1)[-1].lower()
    return host == domain or host.endswith("." + domain)


def extract_site_emails(html: str, domain: str) -> list[str]:
    """Every address on `domain` the page shows a visitor, lower-cased, sorted.
    mailto: links first (with any ?subject= dropped), then visible text with
    entities decoded, then "[at]" spelling. Nothing off-domain, nothing that is
    a file name in disguise."""
    if not html or not domain:
        return []
    domain = domain.lower()
    found: set[str] = set()
    for raw in _MAILTO_RE.findall(html):
        found.add(html_lib.unescape(raw).strip().lower())
    text = html_lib.unescape(_TAG_RE.sub(" ", html))
    for m in _EMAIL_RE.finditer(text):
        found.add(m.group(0).lower())
    for local, host in _OBFUSCATED_RE.findall(text):
        found.add(f"{local}@{_DOT_RE.sub('.', host)}".lower())
    return sorted(
        e for e in found
        if _EMAIL_RE.fullmatch(e) and _on_domain(e, domain) and not _FILE_LIKE_RE.search(e)
    )


def local_kind(email: str) -> str:
    """'general' | 'hiring' | 'person' for an address's local part."""
    local = email.split("@", 1)[0].lower()
    if local in _HIRING_LOCALS:
        return "hiring"
    if local in _GENERAL_LOCALS or local in _NOT_A_PERSON:
        return "general"
    return "person"


def match_contact(email: str, contacts: list[dict]) -> tuple[dict, str] | None:
    """The one contact whose name renders to this local part under an R3
    pattern, with the pattern -- None when nobody or more than one matches."""
    hits = []
    for c in contacts:
        pattern = infer_pattern(c.get("full_name"), email)
        if pattern != "other":
            hits.append((c, pattern))
    return hits[0] if len(hits) == 1 else None


def _pick(emails: list[str], preferred: tuple[str, ...]) -> str | None:
    by_local = {e.split("@", 1)[0]: e for e in emails}
    for local in preferred:
        if local in by_local:
            return by_local[local]
    return emails[0] if emails else None


def _contacts(conn, firm_id: Any) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, full_name FROM contact WHERE firm_id = %s ORDER BY id", (firm_id,))
        return cur.fetchall()


def _firm_emails(conn, firm_id: Any) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT lower(e.email) AS email FROM contact_email e "
            "JOIN contact c ON c.id = e.contact_id WHERE c.firm_id = %s",
            (firm_id,),
        )
        return {r["email"] for r in cur.fetchall()}


def _firm_domain(conn, firm_id: Any) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT domain FROM firm WHERE id = %s", (firm_id,))
        row = cur.fetchone()
        return row["domain"] if row else None


@component(
    "r_site_emails", "R", "Email addresses printed on the firm's own pages -> contacts + claims"
)
def run(ctx: RunContext, *, store: ObjectStore | None = None, **opts: Any) -> RunResult:
    conn = ctx.conn
    result = RunResult()
    store = store or get_store()

    for firm_id in select_firm_ids(
        conn, firm_ids_file=opts.get("firm_ids_file"), limit=opts.get("limit")
    ):
        try:
            domain = _firm_domain(conn, firm_id)
            docs = fetch_documents(conn, firm_id, status_200_only=True)
            docs = [d for d in docs if d.get("object_key")]
            if not domain or not docs:
                result.skipped += 1
                continue

            contacts = _contacts(conn, firm_id)
            people_key = hashlib.sha256(
                "|".join(f"{c['id']}:{c['full_name']}" for c in contacts).encode()
            ).hexdigest()[:16]
            input_hash = compute_input_hash(
                (d["content_hash"] for d in docs), f"{_VERSION}|{people_key}"
            )
            with ctx.once(_COMPONENT_NAME, str(firm_id), input_hash) as should_run:
                if not should_run:
                    result.skipped += 1
                    continue

                found_at: dict[str, str] = {}  # email -> first url it was seen on
                for d in docs:
                    for email in extract_site_emails(read_html(store, d["object_key"]), domain):
                        found_at.setdefault(email, d["url"])
                if not found_at:
                    result.processed += 1
                    continue

                observed_at = max(d["fetched_at"] for d in docs)
                emails = sorted(found_at)
                write_claim(
                    conn, firm_id, "site_emails", emails, _SOURCE, 0.9,
                    found_at[emails[0]], observed_at,
                )
                general = _pick([e for e in emails if local_kind(e) == "general"], _GENERAL_LOCALS)
                hiring = _pick([e for e in emails if local_kind(e) == "hiring"], _HIRING_LOCALS)
                if general:
                    write_claim(
                        conn, firm_id, "general_email", general, _SOURCE, 0.9,
                        found_at[general], observed_at,
                    )
                if hiring:
                    write_claim(
                        conn, firm_id, "hiring_email", hiring, _SOURCE, 0.9,
                        found_at[hiring], observed_at,
                    )

                already = _firm_emails(conn, firm_id)
                attached = 0
                for email in emails:
                    if local_kind(email) != "person" or email in already:
                        continue
                    hit = match_contact(email, contacts)
                    if hit is None:
                        continue
                    contact, pattern = hit
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO contact_email (contact_id, email, status, pattern) "
                            "VALUES (%s, %s, 'unverified', %s) ON CONFLICT DO NOTHING",
                            (contact["id"], email, pattern),
                        )
                        attached += cur.rowcount
                result.notes.append(
                    f"{firm_id}: {len(emails)} on-site address(es), {attached} attached to a "
                    f"named contact, general={'yes' if general else 'no'}, "
                    f"hiring={'yes' if hiring else 'no'}"
                )
            result.processed += 1
        except Exception as exc:  # noqa: BLE001 -- per-firm isolation, never global
            result.failed += 1
            result.notes.append(f"r_site_emails firm={firm_id}: {exc}")
        ctx.checkpoint()

    return result
