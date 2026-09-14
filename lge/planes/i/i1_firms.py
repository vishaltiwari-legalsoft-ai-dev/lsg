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

import re
import uuid
from collections import Counter
from pathlib import Path

from psycopg.types.json import Jsonb

from lge.classify.entity import classify_entity
from lge.classify.roles import classify_role
from lge.ingest.batches import DEFAULT_BATCH_SIZE
from lge.ingest.load import DOMAIN_RULE_VERSION, batched_insert, load_import, register_import
from lge.ingest.normalize import email_domain_plausible, resolve_domain
from lge.norm import NORM_VERSION, norm_name, norm_practice
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
_US_RE = re.compile(r"^\s*(?:us|usa|u\.s\.a?\.?|united states(?: of america)?)\s*$", re.I)

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


# The domain rule (D-017), the email-domain plausibility test and the batched
# insert now live in lge.ingest -- every sheet goes through the same path. The
# old names stay importable for callers and tests that grew up with them.
I1_DOMAIN_RULE_VERSION = DOMAIN_RULE_VERSION
_email_domain_plausible = email_domain_plausible
_resolve_domain = resolve_domain
_batched_insert = batched_insert


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


def _split_name(full_name: str) -> tuple[str, str]:
    tokens = full_name.split()
    return tokens[0], (tokens[-1] if len(tokens) > 1 else "")


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


@component(
    "i1_load",
    "i",
    "Load a firm/contact sheet (any layout, CSV or XLSX) into observation, in batches.",
)
def i1_load(ctx: RunContext, **opts: object) -> RunResult:
    """The sheet goes through lge.ingest: read, sniff the columns, normalise
    every row to the canonical shape, load batch by batch. This wrapper keeps
    the CLI name and adds the per-file summary the vendor loader used to print."""
    raw_path = opts.get("path")
    if not raw_path:
        raise ValueError("i1_load requires --opt path=<csv or xlsx file>")
    path = _resolve_path(str(raw_path))
    if not path.is_file():
        raise FileNotFoundError(f"i1_load: no such file: {path}")

    imp = register_import(
        ctx.conn, path, source_tag=SOURCE,
        batch_size=int(str(opts.get("batch_size", DEFAULT_BATCH_SIZE))),
    )
    if imp["status"] == "loaded":
        return RunResult(skipped=1, notes=[f"unchanged file already loaded: {path}"])

    loaded = load_import(ctx, str(imp["id"]))

    with ctx.conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) AS rows,
                   count(*) FILTER (WHERE domain IS NULL) AS no_domain,
                   count(*) FILTER (WHERE (payload ->> 'domain_from_email')::bool) AS from_email,
                   count(DISTINCT domain) AS domains
            FROM observation WHERE import_id = %s
            """,
            (imp["id"],),
        )
        summary = cur.fetchone()
        # Size contradiction: more than ten contacts on file for a firm the sheet
        # says has at most ten people -- the vendor-headcount trap.
        cur.execute(
            """
            SELECT domain, count(*) AS n FROM observation
            WHERE import_id = %s AND domain IS NOT NULL
              AND coalesce((payload ->> 'size_max')::int, 0) BETWEEN 1 AND 10
            GROUP BY domain HAVING count(*) > 10 ORDER BY count(*) DESC, domain
            """,
            (imp["id"],),
        )
        contradictions = cur.fetchall()
        cur.execute(
            "SELECT coalesce(sum(rows_loaded), 0) AS loaded, coalesce(sum(rows_skipped), 0) "
            "AS skipped FROM import_batch WHERE import_id = %s",
            (imp["id"],),
        )
        counts = cur.fetchone()

    notes = [
        f"import {imp['id']}: {imp['row_count']} rows in {len(imp['column_map']['mapping'])} "
        f"mapped columns, {loaded.processed} batch(es) loaded, {loaded.failed} failed",
        f"rows read: {imp['row_count']}",
        f"rows inserted: {counts['loaded']} (duplicates skipped: {counts['skipped']})",
        f"rows with no domain: {summary['no_domain']}",
        f"rows whose domain came from the email: {summary['from_email']}",
        f"distinct domains: {summary['domains']}",
        f"size-contradiction domains (>10 contacts, file states 1-10 employees): "
        f"{len(contradictions)}",
    ]
    if imp["missing"]:
        notes.append(f"mandatory data the sheet lacks: {', '.join(imp['missing'])}")
    for row in contradictions[:20]:
        notes.append(f"  contradiction: {row['domain']} -> {row['n']} contacts")
    notes.extend(loaded.notes)
    return RunResult(
        processed=int(counts["loaded"]), skipped=int(counts["skipped"]),
        failed=loaded.failed, notes=notes,
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

        canonical_name = _most_common([o["payload"].get("firm_name") for o in obs])
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

        country = _most_common([o["payload"].get("country") for o in obs])
        has_us_state = any(o["payload"].get("state") for o in obs)
        if country and _US_RE.match(country):
            claim_rows.append(
                (firm_id, "country", Jsonb("US"), SOURCE, 0.7,
                 f"sheet's country column: {country}", observed_at)
            )
            counts["country"] += 1
        elif not country and has_us_state:
            claim_rows.append(
                (firm_id, "country", Jsonb("US"), SOURCE, 0.6,
                 "no country column; a US state is given", observed_at)
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
        elif any(_LAW_INDUSTRY_RE.search(o["payload"].get("firm_type") or "") for o in obs):
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
            for tag in (_detect_cms_tag(o["payload"].get("technology")) for o in obs)
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

        description = _most_common([o["payload"].get("firm_type") for o in obs])
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
        employees_range = _most_common([o["payload"].get("firm_size") for o in obs])
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

        size_max = _most_common([o["payload"].get("size_max") for o in obs])
        if n > 10 and size_max is not None and int(size_max) <= 10:
            claim_rows.append(
                (
                    firm_id,
                    "vendor_size_contradiction",
                    Jsonb({"contacts_in_file": n, "stated": employees_range}),
                    SOURCE,
                    0.9,
                    f"{n} contact rows for a firm whose stated size is '{employees_range}'",
                    observed_at,
                )
            )
            counts["vendor_size_contradiction"] += 1

        # What the sheet itself knows about pain and history -- informational
        # claims on the record; never a signal (no first-seen date of our own).
        job_post = _most_common([o["payload"].get("job_post") for o in obs])
        if job_post:
            claim_rows.append(
                (firm_id, "sheet_job_post", Jsonb(job_post), SOURCE, 0.6,
                 "job post column in the sheet", observed_at)
            )
            counts["sheet_job_post"] += 1
        if any(o["payload"].get("contacted_before") for o in obs):
            last = max((o["payload"].get("contacted_at") or "" for o in obs), default="")
            claim_rows.append(
                (firm_id, "contacted_before", Jsonb({"contacted": True, "last": last or None}),
                 SOURCE, 0.8, "sheet says this firm was contacted before", observed_at)
            )
            counts["contacted_before"] += 1

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

    not_people = 0
    legacy = 0
    for row in obs_rows:
        payload = row["payload"]
        firm_id = str(row["firm_id"])
        if "person_name" not in payload:
            legacy += 1  # pre-canonical payload: run ingest_renormalize first
            skipped += 1
            continue
        # The sheet's name is not always a person ("Arizona Litigation Support
        # Court Reporters") and often carries credentials ("Jeremy D. Raincrow,
        # J.D., Ph.D.") -- normalize already applied the one rule every contact
        # source shares (lge.classify.people).
        full_name = payload.get("person_name")
        email = payload.get("email")
        if payload.get("person_name_raw") and not full_name:
            not_people += 1
            skipped += 1
            continue
        if not full_name or not email:
            skipped += 1
            continue

        key = (firm_id, full_name.lower(), email)
        if key in existing_keys:
            skipped += 1
            continue
        existing_keys.add(key)

        title = payload.get("person_title") or None
        role_result = classify_role(title)
        first, last = _split_name(full_name)
        pattern = _email_pattern(first, last, email)

        contact_id = str(uuid.uuid4())
        contact_rows.append(
            (
                contact_id,
                firm_id,
                full_name,
                title,
                role_result.role,
                None,  # bar_number -- R2 (bar record joiner), not this source
                payload.get("linkedin"),
                payload.get("phone"),
                payload.get("phone_e164"),
                payload.get("email_raw") or email,  # the sheet's own address, as given
                SOURCE,
                role_result.confidence,
                None,  # enriched_at -- this is a raw load, not an enrichment pass
            )
        )
        email_rows.append(
            (contact_id, email, "unverified", payload.get("email_status") or None, pattern, None)
        )

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
                "phone_e164",
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
        f"not a person (firm names, page titles, one-word names): {not_people}",
    ]
    if legacy:
        notes.append(f"pre-canonical payloads skipped: {legacy} -- run ingest_renormalize")
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
    legacy = 0
    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT id, payload, name_stem, domain, firm_id FROM observation WHERE source = %s",
            (SOURCE,),
        )
        rows = cur.fetchall()
    for row in rows:
        payload = row["payload"]
        if "firm_name" not in payload:
            legacy += 1  # pre-canonical payload: run ingest_renormalize first
            continue
        name_raw = payload.get("firm_name") or None
        name_stem = norm_name(name_raw)
        domain, _used_email = resolve_domain(
            payload.get("website"), payload.get("email"), name_stem
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
    if legacy:
        notes.append(f"pre-canonical payloads skipped: {legacy} -- run ingest_renormalize")
    if blocked:
        notes.append(
            f"{blocked} RESOLVED observations would change key — not rewritten. They are "
            "attached to firms; detach and re-resolve them deliberately (review)."
        )
    return RunResult(processed=len(changed), skipped=blocked, notes=notes)
