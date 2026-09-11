"""JA6 stage 3 -- the resolution ladder: attach a posting to a real firm, or
don't. context/20-signals/03-agency-filter-and-resolution.md + the identity
ladder in context/30-data-model/03-identity-resolution.md: "a decisive key or
nothing." A wrong match here writes a false hiring history onto a real firm
permanently, so every rung either returns a single unambiguous candidate or
returns nothing -- never a guess.

DB-backed (needs to read `firm` and `ats_slug_map`), unlike ja6_agency.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lge.norm import norm_addr, norm_domain, norm_email_domain, norm_name, norm_phone
from lge.planes.ja.ja6_config import signal_rules
from lge.planes.ja.ja6_types import Posting


@dataclass(frozen=True, slots=True)
class Resolution:
    firm_id: str | None
    rung: int  # 0 = pre-resolved at fetch, 1-6 = the ladder, 7 = no usable city
    confidence: float
    detail: str


# Best-effort US street-address extractor over a posting body. Not a full postal
# parser -- the resolution ladder itself documents rung 5 as "Strong", not
# "Decisive" (context/20-signals/03-agency-filter-and-resolution.md): this only
# has to be good enough to catch the common "123 Main St, Springfield, IL 62704"
# shape a posting states its own address in, and a false positive here still has
# to clear addr_hash equality AND name similarity against a real firm to matter.
_STREET_SUFFIXES = (
    r"St(?:reet)?|Ave(?:nue)?|Blvd|Boulevard|Rd|Road|Dr(?:ive)?|Ln|Lane|Ct|Court|"
    r"Pl(?:ace)?|Pkwy|Parkway|Hwy|Highway|Cir(?:cle)?|Ter(?:race)?|Sq(?:uare)?|"
    r"Plz|Plaza|Trl|Trail|Way|Ctr|Center"
)
_ADDRESS_RE = re.compile(
    r"(?P<street>\d{1,6}\s+[A-Za-z0-9.'\s]{2,60}?\b(?:" + _STREET_SUFFIXES + r")\b)"
    r"[.,]?\s*(?:(?:Suite|Ste|Unit|Floor|Fl|#)\s*[\w-]+[.,]?\s*)?"
    r"(?P<city>[A-Za-z][A-Za-z.\s]{1,40}?),\s*(?P<state>[A-Z]{2})\s+(?P<zip>\d{5})(?:-\d{4})?\b"
)


def extract_street_address(body: str | None) -> tuple[str, str, str, str] | None:
    """(street, city, state, zip5) from the first US-shaped street address found
    in `body`, or None."""
    if not body:
        return None
    m = _ADDRESS_RE.search(body)
    if not m:
        return None
    return m.group("street").strip(), m.group("city").strip(), m.group("state"), m.group("zip")


def _is_usable_city(city: str | None) -> bool:
    if not city or not city.strip():
        return False
    non_city = {v.lower() for v in signal_rules()["resolution"]["non_city_values"]}
    return city.strip().lower() not in non_city


def _excluded_link_hosts() -> frozenset[str]:
    return frozenset(signal_rules()["resolution"]["excluded_link_hosts"])


def resolve(conn, p: Posting) -> Resolution:
    if p.firm_id:
        return Resolution(str(p.firm_id), 0, 1.0, "firm_id already set at fetch (careers page)")

    name_stem = norm_name(p.company_name)

    with conn.cursor() as cur:
        # rung 1 -- apply-email domain, decisive
        email_domain = norm_email_domain(p.apply_email)
        if email_domain:
            cur.execute("SELECT id FROM firm WHERE domain = %s", (email_domain,))
            rows = cur.fetchall()
            if len(rows) == 1:
                return Resolution(
                    str(rows[0]["id"]), 1, 1.0, f"apply-email domain {email_domain}"
                )

        # rung 2 -- outbound link domain, board/ATS hosts excluded, decisive
        excluded = _excluded_link_hosts()
        link_domains = set()
        for link in p.outbound_links or []:
            d = norm_domain(link)
            if d and d not in excluded:
                link_domains.add(d)
        if link_domains:
            cur.execute("SELECT id FROM firm WHERE domain = ANY(%s)", (list(link_domains),))
            firm_ids = {row["id"] for row in cur.fetchall()}
            if len(firm_ids) == 1:
                (only,) = firm_ids
                return Resolution(
                    str(only), 2, 1.0, f"outbound link domain in {sorted(link_domains)}"
                )

        # rung 3 -- phone, decisive
        phone = norm_phone(p.phone_raw)
        if phone:
            cur.execute("SELECT id FROM firm WHERE phone_e164 = %s", (phone,))
            rows = cur.fetchall()
            if len(rows) == 1:
                return Resolution(str(rows[0]["id"]), 3, 1.0, f"phone {phone}")

        # rung 4 -- ATS slug map, decisive. `ats` comes from raw_posting.source
        # ('ats:greenhouse' -> 'greenhouse'), matching ats_slug_map.ats.
        ats = p.source.split(":", 1)[1] if p.source.startswith("ats:") else None
        if ats and p.ats_slug:
            cur.execute(
                "SELECT firm_id FROM ats_slug_map WHERE ats = %s AND slug = %s",
                (ats, p.ats_slug),
            )
            row = cur.fetchone()
            if row:
                return Resolution(
                    str(row["firm_id"]), 4, 1.0, f"ats_slug_map[{ats}][{p.ats_slug}]"
                )

        # rung 5 -- company name + street address (identity rule R3): addr_hash
        # equal AND similarity(name) > threshold. Both required -- address alone
        # merges every firm in an office tower.
        addr = extract_street_address(p.body)
        if addr and name_stem:
            street, city, state, zip5 = addr
            norm = norm_addr(street, city, state, zip5)
            if norm.addr_hash:
                threshold = signal_rules()["resolution"]["addr_name_similarity_threshold"]
                cur.execute(
                    "SELECT id FROM firm WHERE addr_hash = %s AND similarity(name_stem, %s) > %s",
                    (norm.addr_hash, name_stem, threshold),
                )
                rows = cur.fetchall()
                if len(rows) == 1:
                    return Resolution(
                        str(rows[0]["id"]), 5, 0.8, f"addr_hash {norm.addr_hash} + name similarity"
                    )

        # rung 7 first: no usable city is a hard stop before rung 6 is even
        # attempted -- there is nothing to block against.
        if not _is_usable_city(p.city) or not name_stem:
            return Resolution(None, 7, 0.0, f"no usable city (location_raw={p.location_raw!r})")

        # rung 6 -- company name + city, trigram. Accept ONLY when exactly one
        # firm clears the threshold. State filters the candidate set only when
        # BOTH the posting and the candidate firm know a state -- firms in this
        # dataset commonly have a city but no state yet (reconcile() hasn't run),
        # so a firm with state IS NULL is never excluded by this filter; it can
        # still be excluded by the similarity threshold itself.
        threshold = signal_rules()["resolution"]["city_similarity_threshold"]
        if p.state:
            cur.execute(
                "SELECT id FROM firm WHERE lower(city) = lower(%s) "
                "AND (state IS NULL OR state = %s) AND similarity(name_stem, %s) > %s",
                (p.city, p.state, name_stem, threshold),
            )
        else:
            cur.execute(
                "SELECT id FROM firm WHERE lower(city) = lower(%s) "
                "AND similarity(name_stem, %s) > %s",
                (p.city, name_stem, threshold),
            )
        rows = cur.fetchall()
        if len(rows) == 1:
            return Resolution(
                str(rows[0]["id"]), 6, 0.6, f"exactly one city match for {name_stem!r}"
            )

        return Resolution(
            None,
            6,
            0.0,
            f"{len(rows)} candidates for {name_stem!r} in {p.city}, {p.state or '(state unknown)'}",
        )
