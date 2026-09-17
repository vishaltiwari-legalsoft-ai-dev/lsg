"""The field vocabulary: the only names downstream steps read from a canonical
row. A sheet's column becomes one of these or stays in `extra`.

Only two things are mandatory (D-042): a firm name, and *a way to reach the
firm* -- a website, an email (its domain is the website), or a location to
search from. Everything else is research-fillable: the field says where the
engine gets it when the sheet does not carry it, and the import screen says
so instead of calling the sheet incomplete.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    synonyms: tuple[str, ...]
    description: str = ""
    # header words that veto this field even when a synonym matches
    # ("Company City" is the firm's, "City" may be the contact's -- both are
    # city; but "Company Name" must never become person_name)
    vetoes: tuple[str, ...] = ()
    group: str | None = None  # mandatory group this field satisfies
    # where research gets this when the sheet lacks it ("" = nowhere: it is
    # bookkeeping the sheet alone can carry, like "contacted before")
    filled_by: str = ""


FIELDS: tuple[Field, ...] = (
    Field(
        "firm_name", "Firm name",
        ("company name", "formatted company name", "firm name", "law firm", "law firm name",
         "firm", "company", "organization", "organisation", "business name", "account name",
         "employer", "account", "practice name"),
        "The firm as the sheet names it.", group="firm_name",
    ),
    Field(
        "website", "Website",
        ("company url", "website", "web site", "url", "domain", "company website", "homepage",
         "web address", "company domain", "site", "website url", "web"),
        "The firm's site, as given -- verified later.", group="reach",
        filled_by="a web search for the firm, when the sheet's is missing or wrong",
    ),
    Field(
        "city", "City",
        ("company city", "city", "town", "hq city"),
        group="reach", filled_by="the contact page",
    ),
    Field(
        "state", "State",
        ("company state", "state", "province", "region", "st", "state/province", "hq state"),
        group="reach", filled_by="the contact page",
    ),
    Field(
        "zip", "ZIP",
        ("zip", "zip code", "zipcode", "postal code", "postcode", "company zip"),
        group="reach", filled_by="the contact page",
    ),
    Field(
        "address", "Street address",
        ("address", "street", "street address", "company address", "address line 1",
         "address 1", "mailing address", "office address"),
        group="reach", filled_by="the contact page",
    ),
    Field(
        "location", "Location",
        ("location", "company location", "hq", "headquarters", "office location", "metro",
         "market", "city/state", "city, state", "area", "geography"),
        "Free text such as 'Atlanta, GA'.", group="reach", filled_by="the contact page",
    ),
    Field("country", "Country", ("country", "company country", "hq country")),
    Field(
        "firm_size", "Firm size",
        ("employees range", "employees", "employee count", "company size", "size", "headcount",
         "number of employees", "no of employees", "# employees", "attorneys", "attorney count",
         "# of attorneys", "number of attorneys", "lawyers", "firm size", "staff", "staff count",
         "team size"),
        "Headcount or attorney count, as given.",
        filled_by="the team page, LinkedIn's headcount, or the AI reading the site",
    ),
    Field(
        "firm_type", "Firm type",
        ("industry", "company type", "firm type", "type", "practice area", "practice areas",
         "practice", "category", "specialty", "speciality", "description",
         "company description", "sector", "focus", "areas of practice", "practice type",
         "business type", "vertical"),
        "Industry, practice area or description -- a hint, never the tier.",
        filled_by="the practice areas read off the site",
    ),
    Field(
        "job_post", "Job post",
        ("job post", "job posting", "open position", "open role", "hiring", "hiring for",
         "job title posted", "vacancy", "opening", "open jobs", "jobs", "job", "posting",
         "role posted", "position open"),
        "An opening the sheet already knows about.",
        vetoes=("title", "job title"), filled_by="the careers page",
    ),
    Field(
        "person_name", "Contact name",
        ("full name", "name", "contact name", "contact", "person", "attorney name",
         "owner", "owner name", "decision maker", "contact person", "primary contact",
         "lawyer name", "partner name", "principal"),
        vetoes=("company", "firm", "business", "account", "organization", "organisation",
                "domain", "file"),
        filled_by="the people named on the site",
    ),
    Field("first_name", "First name", ("first name", "first", "given name", "forename")),
    Field("last_name", "Last name", ("last name", "last", "surname", "family name")),
    Field(
        "person_title", "Contact title",
        ("job title", "title", "designation", "role", "position title", "position",
         "contact title", "job role", "job function"),
        vetoes=("company", "firm", "post", "posting"),
        filled_by="the title printed beside the name on the site",
    ),
    Field(
        "email", "Email",
        ("business email", "email", "e-mail", "email address", "work email", "contact email",
         "e mail", "mail", "email id", "primary email"),
        vetoes=("status", "quality", "valid", "verified", "pattern", "domain"),
        group="reach",
        filled_by="the contact page, a web search, or the firm's own address pattern",
    ),
    Field(
        "email_status", "Email status",
        ("business email quality", "email status", "email verified", "email quality",
         "verification", "email validation", "valid email", "deliverability"),
    ),
    Field(
        "phone", "Phone",
        ("phone", "phone number", "telephone", "company phone", "direct phone", "mobile",
         "tel", "office phone", "work phone", "contact number", "cell"),
        filled_by="the contact page",
    ),
    Field(
        "linkedin", "LinkedIn",
        ("linkedin", "linkedin url", "linkedin profile", "li url", "linkedin link",
         "person linkedin", "contact linkedin"),
        vetoes=("company linkedin",), filled_by="a web search",
    ),
    Field(
        "contacted_before", "Contacted before",
        ("contacted", "contacted before", "previously contacted", "reached out", "outreach",
         "touched", "contacted?", "already contacted", "prior contact", "outreach status",
         "lead status", "status"),
        vetoes=("email", "website"),
    ),
    Field(
        "contacted_at", "Last contacted",
        ("last contacted", "contacted on", "contacted date", "last touch", "date contacted",
         "last outreach", "last email", "last activity", "contact date", "last contact date",
         "date of contact", "outreach date"),
    ),
    Field(
        "technology", "Technology",
        ("technology", "technologies", "tech stack", "software", "cms", "tools", "tech"),
        filled_by="the site's own code",
    ),
    Field("notes", "Notes", ("notes", "comments", "remarks", "note", "comment", "memo")),
)

BY_NAME: dict[str, Field] = {f.name: f for f in FIELDS}

# A mandatory group is satisfied by any one of its fields being mapped.
MANDATORY_GROUPS: dict[str, tuple[str, ...]] = {
    "firm_name": ("firm_name",),
    "reach": ("website", "email", "city", "state", "zip", "address", "location"),
}

MANDATORY_LABELS: dict[str, str] = {
    "firm_name": "Firm name",
    "reach": "A way to reach the firm: a website, an email, or a location (city, state, "
             "ZIP or address)",
}

# The location fields are one thing to a reader: "where the firm is". Listed
# once, as `location`, when none of them is on the sheet.
_LOCATION_FIELDS = ("city", "state", "zip", "address", "location")

RESEARCH_FILLED: dict[str, str] = {f.name: f.filled_by for f in FIELDS if f.filled_by}


def field_label_of(name: str | None) -> str | None:
    if name is None:
        return None
    return BY_NAME[name].label if name in BY_NAME else name


def missing_mandatory(mapped_fields: set[str]) -> list[str]:
    """The mandatory groups none of whose fields is mapped, in vocabulary order."""
    return [
        group for group, members in MANDATORY_GROUPS.items()
        if not any(m in mapped_fields for m in members)
    ]


def research_fills(mapped_fields: set[str]) -> list[str]:
    """The research-fillable fields the sheet does not carry, in vocabulary
    order -- what the engine will find for itself. A first+last name pair
    counts as a contact name; any one location field counts as a location."""
    mapped = set(mapped_fields)
    if "first_name" in mapped and "last_name" in mapped:
        mapped.add("person_name")
    out: list[str] = []
    for f in FIELDS:
        if not f.filled_by or f.name in mapped:
            continue
        if f.name in _LOCATION_FIELDS:
            continue
        out.append(f.name)
    if not any(m in mapped for m in _LOCATION_FIELDS):
        out.append("location")
    return out


def research_fill_label(name: str) -> str:
    """'Firm size — from the team page, LinkedIn's headcount, or the AI reading
    the site', for the import screen."""
    f = BY_NAME[name]
    return f"{f.label} — from {f.filled_by}"


@dataclass
class ColumnGuess:
    column: str
    field: str | None
    confidence: float
    reason: str
    samples: list[str] = field(default_factory=list)
