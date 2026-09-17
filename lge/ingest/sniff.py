"""Which column is which. Two readers agree or argue: the header (synonyms of
the field vocabulary, with veto words) and the values (what the cells look
like -- emails, URLs, phones, state codes, ZIPs, headcount ranges, dates,
yes/no). A strongly typed value shape beats a misleading header ("Website"
full of email addresses is an email column). Every column gets a guess with a
confidence and a one-line reason, so a person can correct it before loading.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from dateutil import parser as dateutil_parser

from lge.ingest.vocab import BY_NAME, FIELDS, ColumnGuess, missing_mandatory, research_fills

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")
_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?:[/?#].*)?$", re.I
)
_LINKEDIN_RE = re.compile(r"linkedin\.com/(?:in|pub|company)/", re.I)
_PHONE_RE = re.compile(r"^\+?[\d\s().-]{7,}$")
# a date must look like one before dateutil is asked -- it happily reads "4"
_DATEISH_RE = re.compile(
    r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b",
    re.I,
)
_ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")
_HEADCOUNT_RE = re.compile(r"^\d[\d,]*\s*(?:to|-|–|—)\s*\d[\d,]*$|^\d[\d,]*\s*\+$|^\d{1,6}$", re.I)
_YES_NO = {"yes", "no", "y", "n", "true", "false", "1", "0", "contacted", "not contacted"}
_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY", "DC", "PR",
}
_PERSON_NAME_RE = re.compile(r"^[A-Z][a-zA-Z'.-]+(?:\s+[A-Z][a-zA-Z'.-]*){1,3}$")

_HEADER_CLEAN_RE = re.compile(r"[_\-/.:()]+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9 #?]+")

SAMPLE_SIZE = 200


def norm_header(header: str) -> str:
    text = _HEADER_CLEAN_RE.sub(" ", header.lower())
    text = _NON_ALNUM_RE.sub(" ", text)
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Header reading
# ---------------------------------------------------------------------------


def header_guess(header: str) -> tuple[str, float, str] | None:
    h = norm_header(header)
    if not h:
        return None
    h_tokens = set(h.split())
    best: tuple[str, float, str] | None = None
    for f in FIELDS:
        if any(v in h for v in f.vetoes):
            continue
        for syn in f.synonyms:
            if syn == h:
                # A more specific synonym outranks a generic one: "Company City" is
                # the firm's, "City" may be the contact's; "Business Email" beats "Email".
                specificity = min(0.04, 0.01 * len(syn.split()))
                cand = (f.name, round(0.94 + specificity, 2), f"header is '{header}'")
            else:
                s_tokens = set(syn.split())
                contained = s_tokens <= h_tokens or (len(s_tokens) > 1 and h_tokens <= s_tokens)
                if s_tokens and contained:
                    cand = (f.name, 0.7, f"header '{header}' contains '{syn}'")
                else:
                    continue
            if best is None or cand[1] > best[1]:
                best = cand
    return best


# ---------------------------------------------------------------------------
# Value reading
# ---------------------------------------------------------------------------


def _fraction(values: list[str], pred) -> float:
    if not values:
        return 0.0
    return sum(1 for v in values if pred(v)) / len(values)


def _looks_like_date(v: str) -> bool:
    if len(v) < 6 or len(v) > 32 or not _DATEISH_RE.search(v):
        return False
    try:
        dateutil_parser.parse(v, fuzzy=False)
        return True
    except (ValueError, OverflowError):
        return False


def _looks_like_phone(v: str) -> bool:
    # ten digits or more, and not a date written with separators ("2026-03-01")
    digits = sum(c.isdigit() for c in v)
    return bool(_PHONE_RE.match(v)) and digits >= 10 and not _looks_like_date(v)


def shape_guess(values: list[str]) -> tuple[str, float, str] | None:
    """The field a column's non-empty values look like, or None. Ordered from
    most to least specific so an email column is never called a website."""
    vals = [v.strip() for v in values if v and v.strip()][:SAMPLE_SIZE]
    if len(vals) < 3:
        return None
    is_email = lambda v: bool(_EMAIL_RE.match(v))  # noqa: E731
    is_linkedin = lambda v: bool(_LINKEDIN_RE.search(v))  # noqa: E731
    is_url = lambda v: bool(_URL_RE.match(v)) and "@" not in v  # noqa: E731
    is_zip = lambda v: bool(_ZIP_RE.match(v))  # noqa: E731
    is_state = lambda v: v.upper() in _STATE_CODES  # noqa: E731
    is_size = lambda v: bool(_HEADCOUNT_RE.match(v))  # noqa: E731
    is_yes_no = lambda v: v.lower() in _YES_NO  # noqa: E731
    is_name = lambda v: bool(_PERSON_NAME_RE.match(v))  # noqa: E731
    checks: list[tuple[str, float, float, str]] = [
        # field, fraction, min fraction, reason -- most specific first
        ("email", _fraction(vals, is_email), 0.7, "values are email addresses"),
        ("linkedin", _fraction(vals, is_linkedin), 0.5, "values are LinkedIn URLs"),
        ("website", _fraction(vals, is_url), 0.6, "values are web addresses"),
        ("zip", _fraction(vals, is_zip), 0.8, "values are ZIP codes"),
        ("state", _fraction(vals, is_state), 0.8, "values are US state codes"),
        ("contacted_at", _fraction(vals, _looks_like_date), 0.7, "values are dates"),
        ("phone", _fraction(vals, _looks_like_phone), 0.6, "values are phone numbers"),
        ("firm_size", _fraction(vals, is_size), 0.6, "values are headcount ranges"),
        ("contacted_before", _fraction(vals, is_yes_no), 0.8, "values are yes/no"),
        ("person_name", _fraction(vals, is_name), 0.7, "values look like personal names"),
    ]
    for name, frac, minimum, reason in checks:
        if frac >= minimum:
            conf = 0.9 if name in ("email", "linkedin", "zip", "state") else 0.75
            if name in ("contacted_at", "contacted_before", "person_name", "firm_size"):
                conf = 0.55  # a date or a name column could be several things
            return name, round(conf * min(1.0, frac + 0.15), 2), f"{reason} ({frac:.0%})"
    return None


# ---------------------------------------------------------------------------
# The column map
# ---------------------------------------------------------------------------

_STRONG_SHAPES = frozenset({"email", "linkedin", "website", "zip", "state", "phone"})


def _values_win(hg: tuple[str, float, str] | None) -> bool:
    return hg is None or hg[1] < 0.95 or hg[0] in _STRONG_SHAPES


@dataclass
class ColumnMap:
    guesses: list[ColumnGuess]
    mapping: dict[str, str]  # field -> primary column
    secondary: dict[str, list[str]]  # field -> other columns that also carry it
    missing: list[str]  # mandatory groups nothing satisfies
    research_fills: list[str] = field(default_factory=list)  # fields research supplies
    reader: str = "rules"  # which reader produced this map: "rules" | "llm"
    notes: list[str] = field(default_factory=list)  # the reader's remarks on the sheet

    def columns_for(self, name: str) -> list[str]:
        cols = [self.mapping[name]] if name in self.mapping else []
        return cols + self.secondary.get(name, [])

    @property
    def mapped_columns(self) -> set[str]:
        cols = set(self.mapping.values())
        for extra in self.secondary.values():
            cols.update(extra)
        return cols

    def to_dict(self) -> dict[str, Any]:
        return {
            "guesses": [asdict(g) for g in self.guesses],
            "mapping": dict(self.mapping),
            "secondary": {k: list(v) for k, v in self.secondary.items()},
            "missing": list(self.missing),
            "research_fills": list(self.research_fills),
            "reader": self.reader,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ColumnMap:
        return cls(
            guesses=[ColumnGuess(**g) for g in d.get("guesses", [])],
            mapping=dict(d.get("mapping", {})),
            secondary={k: list(v) for k, v in d.get("secondary", {}).items()},
            missing=list(d.get("missing", [])),
            research_fills=list(d.get("research_fills", [])),
            reader=str(d.get("reader", "rules")),
            notes=list(d.get("notes", [])),
        )

    def with_overrides(self, overrides: dict[str, str | None]) -> ColumnMap:
        """A person's corrections: column -> field (or None to unmap). The
        corrected column becomes that field's primary; the old primary drops
        to secondary."""
        guesses = []
        for g in self.guesses:
            if g.column in overrides:
                new_field = overrides[g.column]
                if new_field is not None and new_field not in BY_NAME:
                    raise ValueError(f"unknown field {new_field!r}")
                guesses.append(ColumnGuess(g.column, new_field, 1.0, "set by hand", g.samples))
            else:
                guesses.append(g)
        return _assemble(
            guesses, prefer={c: f for c, f in overrides.items() if f},
            reader=self.reader, notes=self.notes,
        )


def _assemble(
    guesses: list[ColumnGuess],
    prefer: dict[str, str] | None = None,
    *,
    reader: str = "rules",
    notes: list[str] | None = None,
) -> ColumnMap:
    prefer = prefer or {}
    by_field: dict[str, list[ColumnGuess]] = defaultdict(list)
    for g in guesses:
        if g.field:
            by_field[g.field].append(g)
    mapping: dict[str, str] = {}
    secondary: dict[str, list[str]] = {}
    for name, gs in by_field.items():
        def rank(g: ColumnGuess, _name: str = name) -> float:
            return -(1.5 if prefer.get(g.column) == _name else 0.0) - g.confidence

        gs_sorted = sorted(gs, key=rank)
        mapping[name] = gs_sorted[0].column
        if len(gs_sorted) > 1:
            secondary[name] = [g.column for g in gs_sorted[1:]]
    mapped = set(mapping)
    if "first_name" in mapped and "last_name" in mapped:
        mapped.add("person_name")
    return ColumnMap(
        guesses, mapping, secondary, missing_mandatory(mapped),
        research_fills=research_fills(mapped), reader=reader, notes=list(notes or []),
    )


def sniff_columns(headers: list[str], rows: list[dict[str, str]]) -> ColumnMap:
    sample_rows = rows[:SAMPLE_SIZE]
    guesses: list[ColumnGuess] = []
    for h in headers:
        values = [r.get(h, "") for r in sample_rows]
        samples = [v for v in values if v][:3]
        hg = header_guess(h)
        sg = shape_guess(values)
        if hg and sg and hg[0] == sg[0]:
            reason = f"{hg[2]}; {sg[2]}"
            guesses.append(ColumnGuess(h, hg[0], min(0.99, hg[1] + 0.03), reason, samples))
        elif sg and sg[0] in _STRONG_SHAPES and _values_win(hg):
            # Values beat the header when the header is weak, or when it names
            # another typed field ("Website" full of email addresses). An exact
            # header for an untyped field ("Last Touch") keeps its meaning even
            # when the values happen to resemble a typed shape.
            reason = sg[2] if hg is None else f"{sg[2]}, despite header '{h}'"
            guesses.append(ColumnGuess(h, sg[0], sg[1], reason, samples))
        elif hg:
            guesses.append(ColumnGuess(h, hg[0], hg[1], hg[2], samples))
        elif sg:
            guesses.append(ColumnGuess(h, sg[0], sg[1], sg[2], samples))
        else:
            guesses.append(ColumnGuess(h, None, 0.0, "no match -- kept as extra data", samples))
    return _assemble(guesses)


def field_label(name: str) -> str:
    return BY_NAME[name].label if name in BY_NAME else name
