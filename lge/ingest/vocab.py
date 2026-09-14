"""The field vocabulary: the only names downstream steps read from a canonical
row. A sheet's column becomes one of these or stays in `extra`.

Mandatory (must be found before a sheet is worth loading): firm name, website,
location (any of city/state/zip/address/free-text location), firm size and
firm type. Everything else is welcome but optional.
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
        "The firm's site, as given -- verified later.", group="website",
    ),
    Field(
        "city", "City",
        ("company city", "city", "town", "hq city"),
        group="location",
    ),
    Field(
        "state", "State",
        ("company state", "state", "province", "region", "st", "state/province", "hq state"),
        group="location",
    ),
    Field(
        "zip", "ZIP",
        ("zip", "zip code", "zipcode", "postal code", "postcode", "company zip"),
        group="location",
    ),
    Field(
        "address", "Street address",
        ("address", "street", "street address", "company address", "address line 1",
         "address 1", "mailing address", "office address"),
        group="location",
    ),
    Field(
        "location", "Location",
        ("location", "company location", "hq", "headquarters", "office location", "metro",
         "market", "city/state", "city, state", "area", "geography"),
        "Free text such as 'Atlanta, GA'.", group="location",
    ),
    Field("country", "Country", ("country", "company country", "hq country")),
    Field(
        "firm_size", "Firm size",
        ("employees range", "employees", "employee count", "company size", "size", "headcount",
         "number of employees", "no of employees", "# employees", "attorneys", "attorney count",
         "# of attorneys", "number of attorneys", "lawyers", "firm size", "staff", "staff count",
         "team size"),
        "Headcount or attorney count, as given.", group="firm_size",
    ),
    Field(
        "firm_type", "Firm type",
        ("industry", "company type", "firm type", "type", "practice area", "practice areas",
         "practice", "category", "specialty", "speciality", "description",
         "company description", "sector", "focus", "areas of practice", "practice type",
         "business type", "vertical"),
        "Industry, practice area or description -- a hint, never the tier.",
        group="firm_type",
    ),
    Field(
        "job_post", "Job post",
        ("job post", "job posting", "open position", "open role", "hiring", "hiring for",
         "job title posted", "vacancy", "opening", "open jobs", "jobs", "job", "posting",
         "role posted", "position open"),
        "An opening the sheet already knows about.",
        vetoes=("title", "job title"),
    ),
    Field(
        "person_name", "Contact name",
        ("full name", "name", "contact name", "contact", "person", "attorney name",
         "owner", "owner name", "decision maker", "contact person", "primary contact",
         "lawyer name", "partner name", "principal"),
        vetoes=("company", "firm", "business", "account", "organization", "organisation",
                "domain", "file"),
    ),
    Field("first_name", "First name", ("first name", "first", "given name", "forename")),
    Field("last_name", "Last name", ("last name", "last", "surname", "family name")),
    Field(
        "person_title", "Contact title",
        ("job title", "title", "designation", "role", "position title", "position",
         "contact title", "job role", "job function"),
        vetoes=("company", "firm", "post", "posting"),
    ),
    Field(
        "email", "Email",
        ("business email", "email", "e-mail", "email address", "work email", "contact email",
         "e mail", "mail", "email id", "primary email"),
        vetoes=("status", "quality", "valid", "verified", "pattern", "domain"),
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
    ),
    Field(
        "linkedin", "LinkedIn",
        ("linkedin", "linkedin url", "linkedin profile", "li url", "linkedin link",
         "person linkedin", "contact linkedin"),
        vetoes=("company linkedin",),
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
    ),
    Field("notes", "Notes", ("notes", "comments", "remarks", "note", "comment", "memo")),
)

BY_NAME: dict[str, Field] = {f.name: f for f in FIELDS}

# A mandatory group is satisfied by any one of its fields being mapped.
MANDATORY_GROUPS: dict[str, tuple[str, ...]] = {
    "firm_name": ("firm_name",),
    "website": ("website",),
    "location": ("city", "state", "zip", "address", "location"),
    "firm_size": ("firm_size",),
    "firm_type": ("firm_type",),
}

MANDATORY_LABELS: dict[str, str] = {
    "firm_name": "Firm name",
    "website": "Website",
    "location": "Location (city, state, ZIP, address or a location column)",
    "firm_size": "Firm size",
    "firm_type": "Firm type or practice area",
}


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


@dataclass
class ColumnGuess:
    column: str
    field: str | None
    confidence: float
    reason: str
    samples: list[str] = field(default_factory=list)
