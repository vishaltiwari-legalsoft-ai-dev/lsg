"""classify_entity — is this a private law firm at all?

Disqualifier DQ_ENTITY (context/10-icp/06-disqualifiers-and-tracks.md): in-house legal
departments, government, and non-profit legal aid are not private firms — different
budget mechanics entirely. The purchased vendor file tags all of these as "law
practice / 1 to 10 employees": usdoj.gov (40 contacts), orleansda.com (a District
Attorney on a .com), lanwt.org and arlegalaid.org (legal aid), oakland.edu.

Rules are high-precision on purpose. "Smith Legal Services" is a private firm, so the
non-profit patterns only fire on unambiguous phrases, or on "legal services" together
with a .org domain. No rule fired → no claim (absence of evidence is not a verdict).

Bump ENTITY_RULES_VERSION whenever output can change for any input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ENTITY_RULES_VERSION = "1"

_GOV_DOMAIN = re.compile(r"(?:\.gov|\.mil|\.(?:state|co|ci|city|county)\.[a-z]{2}\.us)$")

_GOV_NAME = re.compile(
    r"\b(?:district attorney|attorney general|public defender|county attorney|"
    r"city attorney|state'?s attorney|solicitor general|prosecut(?:or|ing attorney)|"
    r"u\.?s\.? attorney|department of justice|office of the (?:attorney|defender|prosecutor)|"
    r"superior court|circuit court|district court|judicial (?:council|branch|district)|"
    r"county of [a-z]+|city of [a-z]+)\b",
    re.IGNORECASE,
)

_NONPROFIT_NAME = re.compile(
    r"\b(?:legal aid|legal assistance foundation|legal services corporation|"
    r"legal services of |public counsel|pro bono|volunteer lawyers|access to justice|"
    r"bar foundation|innocence project|civil liberties union|aclu|"
    r"defender services|justice center|law project)\b",
    re.IGNORECASE,
)

_ACADEMIC_NAME = re.compile(r"\b(?:university|college|school of law|law school)\b", re.IGNORECASE)


@dataclass(frozen=True)
class EntityResult:
    kind: str | None          # private_firm | inhouse | gov | nonprofit | directory_stub
    confidence: float
    evidence: str | None


def classify_entity(name: str | None, domain: str | None) -> EntityResult:
    """Deterministic entity classification from a firm name and its registered domain.

    Order matters: a government office outranks everything, then non-profits, then
    academic institutions (their counsel's office or clinic is not a private firm).
    """
    n = (name or "").strip()
    d = (domain or "").strip().lower()

    if d and _GOV_DOMAIN.search(d):
        return EntityResult("gov", 0.95, f"domain {d} is a government TLD")
    if n and (m := _GOV_NAME.search(n)):
        return EntityResult("gov", 0.85, f"name names a government office: {m.group(0)!r}")
    if n and (m := _NONPROFIT_NAME.search(n)):
        return EntityResult("nonprofit", 0.85, f"name names a non-profit: {m.group(0)!r}")
    if d.endswith(".org") and re.search(r"\blegal services\b", n, re.IGNORECASE):
        return EntityResult("nonprofit", 0.7, f"'legal services' on a .org domain ({d})")
    if d.endswith(".edu"):
        return EntityResult("inhouse", 0.85, f"domain {d} is an academic institution")
    if n and (m := _ACADEMIC_NAME.search(n)):
        return EntityResult("inhouse", 0.8, f"name names an academic institution: {m.group(0)!r}")
    return EntityResult(None, 0.0, None)
