"""A batch's canonical rows -> what is missing, malformed or duplicated, and
one score. Run before loading (is this sheet worth it?) and again after the
website check and site read (did the data get richer?)."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class HealthReport:
    rows: int = 0
    firm_name_missing: int = 0
    website_missing: int = 0
    website_malformed: int = 0  # something was given, no usable domain came of it
    domain_from_email: int = 0
    location_missing: int = 0
    size_missing: int = 0
    type_missing: int = 0
    person_rows: int = 0
    junk_person_names: int = 0
    invalid_emails: int = 0
    duplicate_domain_rows: int = 0  # rows beyond the first per domain (contacts at one firm)
    distinct_domains: int = 0
    contacted_before: int = 0
    job_posts: int = 0
    score: int = 0  # 0-100, mandatory-field coverage
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess(rows: list[dict[str, Any]]) -> HealthReport:
    r = HealthReport(rows=len(rows))
    if not rows:
        r.notes.append("no rows")
        return r
    domains: Counter[str] = Counter()
    for row in rows:
        if not row.get("firm_name"):
            r.firm_name_missing += 1
        if not row.get("website") and not row.get("domain"):
            r.website_missing += 1
        elif row.get("website") and not row.get("domain"):
            r.website_malformed += 1
        if row.get("domain_from_email"):
            r.domain_from_email += 1
        if not any(row.get(k) for k in ("city", "state", "zip", "address", "location")):
            r.location_missing += 1
        if not row.get("firm_size"):
            r.size_missing += 1
        if not row.get("firm_type"):
            r.type_missing += 1
        if row.get("person_name_raw"):
            r.person_rows += 1
            if not row.get("is_person"):
                r.junk_person_names += 1
        if row.get("email_raw") and not row.get("email_valid"):
            r.invalid_emails += 1
        if row.get("domain"):
            domains[row["domain"]] += 1
        if row.get("contacted_before"):
            r.contacted_before += 1
        if row.get("job_post"):
            r.job_posts += 1
    r.distinct_domains = len(domains)
    r.duplicate_domain_rows = sum(n - 1 for n in domains.values() if n > 1)

    n = len(rows)
    coverage = [
        1 - r.firm_name_missing / n,
        1 - (r.website_missing + r.website_malformed) / n,
        1 - r.location_missing / n,
        1 - r.size_missing / n,
        1 - r.type_missing / n,
    ]
    r.score = round(100 * sum(coverage) / len(coverage))
    if r.website_malformed:
        r.notes.append(f"{r.website_malformed} website value(s) yield no usable domain")
    if r.junk_person_names:
        r.notes.append(f"{r.junk_person_names} contact name(s) are not people")
    if r.invalid_emails:
        r.notes.append(f"{r.invalid_emails} email value(s) are not addresses")
    return r
