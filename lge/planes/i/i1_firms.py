"""I1 — the purchased firm/contact dataset (source tag: internal_firms).

context/50-first-party/04-firm-dataset.md and context/50-first-party/02-one-door-rule.md.
Every row enters through `observation`, exactly like a scraped source — this module
never writes `firm` directly. Identity resolution (owned elsewhere) later sets
observation.firm_id; i1_claims and i1_contacts only act on rows it has already
resolved.

Provenance decision (recorded again in config/sources/vendor_firms.yml): this is a
*purchased* dataset, so it ranks at directory tier — below Places, same staleness
profile as Justia/Avvo. That ranking is reconcile()'s business (I7), not this
loader's; nothing here writes to `firm`.

The vendor-headcount trap (context/10-icp/04-size-and-need-proxies.md): Employees
Range is total headcount, not attorney count, and this file's own profile proves the
point -- quarles.com carries 58 contacts and usdoj.gov 40, both "1 to 10" by the
vendor's own field. i1_claims records that field as `vendor_headcount_range`
(informational, no firm column) and flags the contradiction; it never writes
`attorney_count`.
"""

from __future__ import annotations

import csv
import hashlib
import re
import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from lge.classify.entity import classify_entity
from lge.classify.roles import classify_role
from lge.norm import NORM_VERSION, norm_domain, norm_email_domain, norm_name, norm_practice
from lge.registry import RunContext, RunResult, component
from lge.settings import PROJECT_ROOT

SOURCE = "internal_firms"

# Vendor Technology-column tag text (lowercase, as it appears in the comma list) ->
# the CMS slug used in config/tech_fingerprints.yml. detect_tech() in
# lge/classify/tech.py matches HOST-anchored regex against fetched HTML -- this
# dataset instead hands us the vendor's own free-text tag, so it needs its own,
# much simpler mapping. Kept to "cms" category names only (never "intake") because
# cms_detected is specifically a case-management-system attribute; entries with more
# than one vendor spelling (rocket matter / rocketmatter, leap / "leap legal
# software", needles / neos) list every spelling seen.
_VENDOR_CMS_TAGS: dict[str, str] = {
    "filevine": "filevine",
    "clio": "clio",
    "goclio": "clio",
    "casepeer": "casepeer",
    "mycase": "mycase",
    "litify": "litify",
    "smartadvocate": "smartadvocate",
    "practicepanther": "practicepanther",
    "cosmolex": "cosmolex",
    "smokeball": "smokeball",
    "rocket matter": "rocket_matter",
    "rocketmatter": "rocket_matter",
    "leap legal software": "leap",
    "leap": "leap",
    "needles": "needles",
    "neos": "needles",
}

# entity_kind='gov': .gov/.mil, or the historical "state.XX.us" state-government
# suffix. norm_domain() always reduces a host under that suffix to exactly this
# eTLD+1 shape (e.g. "oag.state.tx.us" -> "state.tx.us"), so an exact match is
# correct -- not just endswith.
_GOV_STATE_RE = re.compile(r"^state\.[a-z]{2}\.us$")

_LAW_INDUSTRY_RE = re.compile(r"\b(law|legal)\b", re.IGNORECASE)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")


def _resolve_path(raw: str) -> Path:
    """A bare/relative path is resolved against the project root so the CLI's
    `--opt path=data/in/x.csv` and a test's absolute tmp path both work."""
    p = Path(raw)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


def _is_government_domain(domain: str | None) -> bool:
    if not domain:
        return False
    if domain.endswith(".gov") or domain.endswith(".mil"):
        return True
    return bool(_GOV_STATE_RE.match(domain))


# Bump when the domain derivation below can change for any input. Stored in
# observation.norm_versions["i1_domain_rule"] so i1_rekey knows which rows were keyed
# under an older rule — the norm_version mechanism: recompute, never re-harvest.
I1_DOMAIN_RULE_VERSION = "2"


def _email_domain_plausible(email_domain: str, name_stem: str | None) -> bool:
    """An email domain may stand in as the firm's identity key only when it visibly
    belongs to the firm: a name-stem token of >=4 chars appears in the domain's
    registered label, or the stem's initials (>=2 tokens) do.

    Why so strict: a contact's email can belong to a DIFFERENT organisation — a
    previous firm, a university, a corporate employer. In the purchased file,
    "Faggiano & Associates" carried an adlercohen.com address (another law firm),
    "Bernice Lake PC" a mattel.com one. Used as an identity key, that merges two
    firms — the invisible, unrecoverable direction. Refusing costs one domainless
    firm — the visible, cheap direction.
    """
    if not name_stem:
        return False
    label = re.sub(r"[^a-z0-9]", "", email_domain.split(".", 1)[0].lower())
    tokens = [t for t in re.split(r"\s+", name_stem.lower()) if t]
    if any(len(t) >= 4 and t in label for t in tokens):
        return True
    if len(tokens) >= 2:
        initials = "".join(t[0] for t in tokens)
        if len(initials) >= 2 and initials in label:
            return True
    return False


def _resolve_domain(
    company_url: str | None, business_email: str | None, name_stem: str | None = None
) -> tuple[str | None, bool]:
    """(domain, from_email). The Company URL wins. When it yields nothing (blank,
    shared-host-blocked, garbage like "513.2664"), the email's domain is used ONLY
    if it plausibly belongs to the firm — see _email_domain_plausible."""
    domain = norm_domain(company_url)
    if domain is not None:
        return domain, False
    domain = norm_email_domain(business_email)
    if domain is not None and _email_domain_plausible(domain, name_stem):
        return domain, True
    return None, False


def _pick_city(row: dict[str, str]) -> str | None:
    # Company City is far more complete than City (the contact's own city, which
    # can differ from the firm's -- row 1 of the real file is a Houston contact at
    # a Dallas firm) -- prefer it, fall back to City.
    for key in ("Company City", "City"):
        value = (row.get(key) or "").strip()
        if value:
            return value
    return None


def _source_key(email: str | None, row: dict[str, str], fieldnames: Sequence[str]) -> str:
    if email and email.strip():
        return hashlib.sha1(email.strip().lower().encode("utf-8")).hexdigest()
    # Fallback: sha1 of the whole row, joined on a separator that can't appear in a
    # CSV field value (unlike ",") so two different rows can't collide by accident.
    joined = "\x1f".join((row.get(f) or "") for f in fieldnames)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def _detect_cms_tag(technology: str | None) -> str | None:
    """First legal-CMS vendor tag found in a Technology comma-list (the raw tag
    text, for evidence -- not the slug), or None."""
    if not technology:
        return None
    for tag in (t.strip().lower() for t in technology.split(",")):
        if tag in _VENDOR_CMS_TAGS:
            return tag
    return None


def _most_common(values: list[str | None]) -> str | None:
    present = [v for v in values if v]
    if not present:
        return None
    return Counter(present).most_common(1)[0][0]


def _alnum(s: str | None) -> str:
    return _NON_ALNUM_RE.sub("", (s or "").lower())


def _email_pattern(first: str | None, last: str | None, email: str | None) -> str:
    """first.last | flast | first | firstl | last | other, from the local part of
    `email` against First/Last Name. Approximate on purpose -- this labels the
    vendor's own address for reporting, it is not itself a verification signal."""
    if not first or not last or not email or "@" not in email:
        return "other"
    local = email.split("@", 1)[0]
    f, l = _alnum(first), _alnum(last)  # noqa: E741
    if not f or not l:
        return "other"
    if local.lower() == f"{f}.{l}":
        return "first.last"
    local_alnum = _alnum(local)
    if local_alnum == f"{f[0]}{l}":
        return "flast"
    if local_alnum == f"{f}{l[0]}":
        return "firstl"
    if local_alnum == f:
        return "first"
    if local_alnum == l:
        return "last"
    return "other"


def _batched_insert(
    cur: psycopg.Cursor,
    table: str,
    columns: Sequence[str],
    conflict_cols: Sequence[str],
    rows: Sequence[tuple],
    batch_size: int = 2000,
    update_cols: Sequence[str] = (),
) -> int:
    """Multi-row `INSERT ... VALUES (...), (...) ON CONFLICT (conflict_cols) DO
    NOTHING`, batched so one call handles 37k rows in a handful of round trips.
    Returns rows actually inserted (cur.rowcount summed across batches) -- rows
    skipped by the conflict are not counted, which is how callers report
    duplicates without a second query."""
    if not rows:
        return 0
    col_list = ", ".join(columns)
    conflict_list = ", ".join(conflict_cols)
    n_cols = len(columns)
    inserted = 0
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        placeholders = ", ".join("(" + ", ".join(["%s"] * n_cols) + ")" for _ in chunk)
        if update_cols:
            # Deterministic re-derivation: a corrected rule over the same observation
            # updates the claim in place; an unchanged re-run writes nothing.
            sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
            old = ", ".join(f"{table}.{c}" for c in update_cols)
            new = ", ".join(f"EXCLUDED.{c}" for c in update_cols)
            action = f"DO UPDATE SET {sets} WHERE ({old}) IS DISTINCT FROM ({new})"
        else:
            action = "DO NOTHING"
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES {placeholders} "  # noqa: S608
            f"ON CONFLICT ({conflict_list}) {action}"
        )
        params = [v for row in chunk for v in row]
        cur.execute(sql, params)
        inserted += cur.rowcount
    return inserted


@component(
    "i1_load",
    "i",
    "Load the purchased firm/contact CSV into observation (source=internal_firms).",
)
def i1_load(ctx: RunContext, **opts: object) -> RunResult:
    raw_path = opts.get("path")
    if not raw_path:
        raise ValueError("i1_load requires --opt path=<csv file>")
    path = _resolve_path(str(raw_path))
    if not path.is_file():
        raise FileNotFoundError(f"i1_load: no such file: {path}")

    file_bytes = path.read_bytes()
    input_hash = hashlib.sha256(file_bytes).hexdigest()
    entity_id = str(path.resolve())
    # Deterministic per file: two loads of the same bytes produce the same
    # fetched_at, so observation's UNIQUE (source, source_key, fetched_at) makes a
    # retry's INSERT a safe, empty no-op via ON CONFLICT DO NOTHING below -- belt
    # and braces alongside ctx.once, which is what actually skips a re-run.
    fetched_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)

    with ctx.once("i1_load", entity_id, input_hash) as should_run:
        if not should_run:
            return RunResult(skipped=1, notes=[f"unchanged file already loaded: {path}"])

        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames or []
            rows = list(reader)

        observation_rows: list[tuple] = []
        no_domain = 0
        from_email = 0
        domain_counts: Counter[str] = Counter()
        norm_versions = Jsonb(
            {
                "norm_domain": NORM_VERSION["norm_domain"],
                "norm_name": NORM_VERSION["norm_name"],
                "i1_domain_rule": I1_DOMAIN_RULE_VERSION,
            }
        )

        for row in rows:
            business_email = (row.get("Business Email") or "").strip()
            company_url = (row.get("Company URL") or "").strip()
            name_raw = (
                row.get("Formatted Company Name") or row.get("Company Name") or ""
            ).strip() or None
            name_stem = norm_name(name_raw)
            domain, used_email = _resolve_domain(company_url, business_email, name_stem)
            if domain is None:
                no_domain += 1
            else:
                domain_counts[domain] += 1
                if used_email:
                    from_email += 1
            city = _pick_city(row)
            source_key = _source_key(business_email, row, fieldnames)

            observation_rows.append(
                (
                    SOURCE,
                    source_key,
                    None,  # firm_id -- set later by identity resolution
                    Jsonb(row),
                    fetched_at,
                    name_raw,
                    name_stem,
                    domain,
                    None,  # phone_e164 -- not in this vendor file
                    None,  # addr_hash -- no street data
                    None,  # zip5
                    city,
                    None,  # state -- never embedded in City/Company City (checked)
                    norm_versions,
                )
            )

        with ctx.conn.cursor() as cur:
            inserted = _batched_insert(
                cur,
                "observation",
                (
                    "source",
                    "source_key",
                    "firm_id",
                    "payload",
                    "fetched_at",
                    "name_raw",
                    "name_stem",
                    "domain",
                    "phone_e164",
                    "addr_hash",
                    "zip5",
                    "city",
                    "state",
                    "norm_versions",
                ),
                ("source", "source_key", "fetched_at"),
                observation_rows,
            )

        contradictions = sorted(
            ((d, n) for d, n in domain_counts.items() if n > 10),
            key=lambda kv: (-kv[1], kv[0]),
        )

        notes = [
            f"rows read: {len(rows)}",
            f"rows inserted: {inserted} (duplicates skipped: {len(rows) - inserted})",
            f"rows with no domain: {no_domain}",
            f"rows whose domain came from the email: {from_email}",
            f"distinct domains: {len(domain_counts)}",
            f"size-contradiction domains (>10 contacts, file states 1-10 employees): "
            f"{len(contradictions)}",
        ]
        for d, n in contradictions[:20]:
            notes.append(f"  contradiction: {d} -> {n} contacts")

        return RunResult(
            processed=len(rows), skipped=len(rows) - inserted, failed=0, notes=notes
        )


@component(
    "i1_claims",
    "i",
    "Aggregate resolved internal_firms observations into firm_attribute claims.",
)
def i1_claims(ctx: RunContext, **opts: object) -> RunResult:
    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT payload, fetched_at, domain, city, name_raw, firm_id FROM observation "
            "WHERE source = %s AND firm_id IS NOT NULL",
            (SOURCE,),
        )
        obs_rows = cur.fetchall()

    by_firm: dict[str, list[dict]] = {}
    for row in obs_rows:
        by_firm.setdefault(str(row["firm_id"]), []).append(row)

    claim_rows: list[tuple] = []
    counts: Counter[str] = Counter()

    for firm_id, obs in by_firm.items():
        n = len(obs)
        observed_at = max(o["fetched_at"] for o in obs)
        evidence_n = f"most common of {n} vendor contact row(s)"

        canonical_name = _most_common([o["payload"].get("Formatted Company Name") for o in obs])
        if canonical_name:
            claim_rows.append(
                (firm_id, "canonical_name", Jsonb(canonical_name), SOURCE, 0.5, evidence_n,
                 observed_at)
            )
            counts["canonical_name"] += 1

        city = _most_common([o["city"] for o in obs])
        if city:
            claim_rows.append(
                (firm_id, "city", Jsonb(city), SOURCE, 0.5, evidence_n, observed_at)
            )
            counts["city"] += 1

        claim_rows.append(
            (
                firm_id,
                "country",
                Jsonb("US"),
                SOURCE,
                0.7,
                "vendor dataset Country column is United States for every contact",
                observed_at,
            )
        )
        counts["country"] += 1

        firm_domain = _most_common([o["domain"] for o in obs])
        firm_name = _most_common([o["name_raw"] for o in obs])
        # Government offices, non-profit legal aid and academic institutions are
        # not private firms (DQ_ENTITY). The vendor tags them all "law practice".
        entity = classify_entity(firm_name, firm_domain)
        if entity.kind:
            claim_rows.append(
                (
                    firm_id,
                    "entity_kind",
                    Jsonb(entity.kind),
                    SOURCE,
                    entity.confidence,
                    entity.evidence,
                    observed_at,
                )
            )
            counts[f"entity_kind:{entity.kind}"] += 1
        elif any(_LAW_INDUSTRY_RE.search(o["payload"].get("Industry") or "") for o in obs):
            claim_rows.append(
                (
                    firm_id,
                    "entity_kind",
                    Jsonb("private_firm"),
                    SOURCE,
                    0.4,
                    "vendor Industry column indicates a law practice",
                    observed_at,
                )
            )
            counts["entity_kind:private_firm"] += 1

        matched_tags = [
            tag
            for tag in (_detect_cms_tag(o["payload"].get("Technology")) for o in obs)
            if tag
        ]
        if matched_tags:
            tag = _most_common(matched_tags)
            slug = _VENDOR_CMS_TAGS[tag]
            claim_rows.append(
                (
                    firm_id,
                    "cms_detected",
                    Jsonb(slug),
                    SOURCE,
                    0.5,
                    f"vendor technology tag: {tag}",
                    observed_at,
                )
            )
            counts["cms_detected"] += 1

        description = _most_common([o["payload"].get("Description") for o in obs])
        if description and description.strip():
            # A HINT, never primary_practice. Doc 02 §4: vendor practice data is
            # "coarse — site classification still runs"; the firm dataset is a
            # discovery accelerator, not a qualification source. A keyword read of a
            # one-line marketing blurb disqualified real prospects when it was allowed
            # to set primary_practice ("representing employees in all aspects of
            # employment" -> appellate -> DQ_NOVOLUME). The hint only steers which
            # firms get crawled; practice comes from the firm's own site.
            result = norm_practice([(description, 0)])
            if result.primary is not None:
                conf = min(0.5, result.confidence)
                snippet = description[:200]
                hint = {
                    "primary": result.primary,
                    "areas": [slug for slug, _share in result.areas],
                }
                claim_rows.append(
                    (firm_id, "vendor_practice_hint", Jsonb(hint), SOURCE, conf, snippet,
                     observed_at)
                )
                counts["vendor_practice_hint"] += 1

        # Informational -- no firm column. NEVER attorney_count: vendor headcount is
        # total headcount, not attorneys (the vendor-headcount trap this whole
        # component exists to guard against).
        employees_range = _most_common([o["payload"].get("Employees Range") for o in obs])
        if employees_range:
            claim_rows.append(
                (
                    firm_id,
                    "vendor_headcount_range",
                    Jsonb(employees_range),
                    SOURCE,
                    0.5,
                    "vendor Employees Range column",
                    observed_at,
                )
            )
            counts["vendor_headcount_range"] += 1

        if n > 10:
            claim_rows.append(
                (
                    firm_id,
                    "vendor_size_contradiction",
                    Jsonb({"contacts_in_file": n, "stated": "1 to 10"}),
                    SOURCE,
                    0.9,
                    f"{n} vendor contact rows for a firm whose stated range is '1 to 10'",
                    observed_at,
                )
            )
            counts["vendor_size_contradiction"] += 1

    with ctx.conn.cursor() as cur:
        inserted = _batched_insert(
            cur,
            "firm_attribute",
            ("firm_id", "attr", "value", "source", "confidence", "evidence", "observed_at"),
            ("firm_id", "attr", "source", "observed_at"),
            claim_rows,
            update_cols=("value", "confidence", "evidence"),
        )

    notes = [
        f"firms processed: {len(by_firm)}",
        f"claim rows attempted: {len(claim_rows)}",
        f"claim rows inserted: {inserted}",
    ]
    for k, v in sorted(counts.items()):
        notes.append(f"  {k}: {v}")

    return RunResult(
        processed=len(by_firm), skipped=len(claim_rows) - inserted, failed=0, notes=notes
    )


@component(
    "i1_contacts",
    "i",
    "Resolved internal_firms observations -> contact + contact_email.",
)
def i1_contacts(ctx: RunContext, **opts: object) -> RunResult:
    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT payload, firm_id FROM observation "
            "WHERE source = %s AND firm_id IS NOT NULL ORDER BY id",
            (SOURCE,),
        )
        obs_rows = cur.fetchall()

        cur.execute(
            "SELECT c.firm_id, lower(c.full_name) AS full_name, ce.email "
            "FROM contact c JOIN contact_email ce ON ce.contact_id = c.id "
            "WHERE c.source = %s",
            (SOURCE,),
        )
        existing_keys = {(str(r["firm_id"]), r["full_name"], r["email"]) for r in cur.fetchall()}

    contact_rows: list[tuple] = []
    email_rows: list[tuple] = []
    skipped = 0

    for row in obs_rows:
        payload = row["payload"]
        firm_id = str(row["firm_id"])
        full_name = (payload.get("Full Name") or "").strip()
        email_raw = (payload.get("Business Email") or "").strip()
        email = email_raw.lower()
        if not full_name or not email:
            skipped += 1
            continue

        key = (firm_id, full_name.lower(), email)
        if key in existing_keys:
            skipped += 1
            continue
        existing_keys.add(key)

        title = (payload.get("Job Title") or "").strip() or None
        role_result = classify_role(title)
        linkedin = (payload.get("Linkedin") or "").strip() or None
        pattern = _email_pattern(payload.get("First Name"), payload.get("Last Name"), email)
        vendor_status = (payload.get("Business Email Quality") or "").strip() or None

        contact_id = str(uuid.uuid4())
        contact_rows.append(
            (
                contact_id,
                firm_id,
                full_name,
                title,
                role_result.role,
                None,  # bar_number -- R2 (bar record joiner), not this source
                linkedin,
                None,  # phone_direct -- not in this vendor file
                email_raw,  # email_raw -- the vendor's own claimed address, as given
                SOURCE,
                role_result.confidence,
                None,  # enriched_at -- this is a raw load, not an enrichment pass
            )
        )
        email_rows.append((contact_id, email, "unverified", vendor_status, pattern, None))

    with ctx.conn.cursor() as cur:
        inserted_contacts = _batched_insert(
            cur,
            "contact",
            (
                "id",
                "firm_id",
                "full_name",
                "title",
                "role",
                "bar_number",
                "linkedin_url",
                "phone_direct",
                "email_raw",
                "source",
                "confidence",
                "enriched_at",
            ),
            ("id",),
            contact_rows,
        )
        inserted_emails = _batched_insert(
            cur,
            "contact_email",
            ("contact_id", "email", "status", "vendor_status", "pattern", "verified_at"),
            ("contact_id", "email"),
            email_rows,
        )

    notes = [
        f"internal_firms observations considered: {len(obs_rows)}",
        f"contacts inserted: {inserted_contacts}",
        f"contact_email rows inserted: {inserted_emails}",
        f"skipped (duplicate person, or missing name/email): {skipped}",
    ]
    return RunResult(processed=len(contact_rows), skipped=skipped, failed=0, notes=notes)


@component(
    "i1_rekey",
    plane="I",
    description="recompute internal_firms match keys under the current rules (norm_version)",
)
def i1_rekey(ctx: RunContext, **opts: str) -> RunResult:
    """Re-derive observation.domain / name_stem from the stored payload whenever the
    rules that computed them have changed — the spec's norm_version mechanism:
    "know which rows were computed under the old rule so they can be recomputed
    without re-crawling". The payload (the raw vendor row) is never touched.

    Only UNRESOLVED observations (firm_id IS NULL) are re-keyed. A resolved row whose
    key would change is reported, not rewritten: changing its key would silently
    desync it from its firm, and unpicking a merge is a reviewed action.
    """
    changed: list[tuple] = []
    blocked = 0
    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT id, payload, name_stem, domain, firm_id FROM observation WHERE source = %s",
            (SOURCE,),
        )
        rows = cur.fetchall()
    for row in rows:
        payload = row["payload"]
        name_raw = (
            payload.get("Formatted Company Name") or payload.get("Company Name") or ""
        ).strip() or None
        name_stem = norm_name(name_raw)
        domain, _used_email = _resolve_domain(
            (payload.get("Company URL") or "").strip(),
            (payload.get("Business Email") or "").strip(),
            name_stem,
        )
        if (domain, name_stem) == (row["domain"], row["name_stem"]):
            continue
        if row["firm_id"] is not None:
            blocked += 1
            continue
        changed.append((domain, name_stem, row["id"]))

    if changed and not ctx.dry_run:
        with ctx.conn.cursor() as cur:
            cur.executemany(
                "UPDATE observation SET domain = %s, name_stem = %s, "
                "norm_versions = norm_versions || jsonb_build_object("
                "'i1_domain_rule', %s::text, 'norm_domain', %s::text, 'norm_name', %s::text) "
                "WHERE id = %s",
                [
                    (d, n, I1_DOMAIN_RULE_VERSION, NORM_VERSION["norm_domain"],
                     NORM_VERSION["norm_name"], i)
                    for d, n, i in changed
                ],
            )
    notes = [f"re-keyed {len(changed)} unresolved observations under i1_domain_rule "
             f"v{I1_DOMAIN_RULE_VERSION}"]
    if blocked:
        notes.append(
            f"{blocked} RESOLVED observations would change key — not rewritten. They are "
            "attached to firms; detach and re-resolve them deliberately (review)."
        )
    return RunResult(processed=len(changed), skipped=blocked, notes=notes)
