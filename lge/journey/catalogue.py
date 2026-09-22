"""The journey as the Email journey screen shows it (D-057): each email's
purpose, which copy file serves it under which condition -- in plain words --
the fill-ins a person may use, and the checks an edit must pass.

It mirrors the selection in build.py. tests/journey/test_catalogue.py holds the
two together: every copy file is listed once, and every file build.py reports
for an example firm is listed under the email it rendered. Pure -- no DB.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from lge.journey.render import load_template
from lge.journey.select import load_config

TemplateKind = Literal["email", "paragraph"]


@dataclass(frozen=True, slots=True)
class CatalogueTemplate:
    id: str
    path: str  # under journey/copy/
    step: int
    kind: TemplateKind
    used_when: str
    # An email assembled around a paragraph names the slot it must keep.
    keeps: str | None = None


@dataclass(frozen=True, slots=True)
class StepInfo:
    title: str
    purpose: str
    varies_by: str


STEPS: dict[int, StepInfo] = {
    1: StepInfo(
        "The pain",
        "One thing the firm's own record shows it needs, and one question.",
        "Chosen by the pain found. Hourly firms get their own.",
    ),
    2: StepInfo(
        "The specific work",
        "Names the task we would take on, not a job title.",
        "Chosen by the pain found and the tier.",
    ),
    3: StepInfo(
        "The arithmetic",
        "Why those hours cost this firm money, in the terms of how it bills.",
        "Chosen by the fee model. Never a general version.",
    ),
    4: StepInfo(
        "A comparable firm",
        "A firm of the same shape that started the same way.",
        "The same for every firm.",
    ),
    5: StepInfo(
        "The worry, answered first",
        "Confidentiality and supervision, before anyone has to ask.",
        "The same for every firm. Names the case system when it is known.",
    ),
    6: StepInfo(
        "A second seat",
        "A different, smaller role, in case the first was the wrong one.",
        "The same for every firm.",
    ),
    7: StepInfo(
        "The other person",
        "Offers to talk to the office manager instead.",
        "The same for every firm.",
    ),
    8: StepInfo(
        "Still open?",
        "Asks again while the job post is still up.",
        "Sent only while the job post is still up.",
    ),
    9: StepInfo(
        "Closing the loop",
        "No pressure, and the door left open.",
        "The same for every firm.",
    ),
}

_T = CatalogueTemplate
TEMPLATES: tuple[CatalogueTemplate, ...] = (
    _T("1-open-role", "touch1/1a.md", 1, "email",
       "An open job post, when the firm's case system is known", keeps="middle_paragraph"),
    _T("1-open-role-no-system", "touch1/1a_no_cms.md", 1, "email",
       "An open job post, when the case system is not known", keeps="middle_paragraph"),
    _T("1-paragraph-pi", "touch1/_middle_1a.md", 1, "paragraph",
       "Its middle paragraph for personal injury firms (tier 1A), case system known"),
    _T("1-paragraph-pi-no-system", "touch1/_middle_1a_no_cms.md", 1, "paragraph",
       "Its middle paragraph for personal injury firms (tier 1A), case system not known"),
    _T("1-paragraph-immigration", "touch1/_middle_1b.md", 1, "paragraph",
       "Its middle paragraph for immigration firms (tier 1B)"),
    _T("1-paragraph-fee-shifting", "touch1/_middle_2.md", 1, "paragraph",
       "Its middle paragraph for fee-shifting firms (tier 2)"),
    _T("1-paragraph-flat-fee", "touch1/_middle_3.md", 1, "paragraph",
       "Its middle paragraph for flat-fee volume firms (tier 3)"),
    _T("1-reposted-role", "touch1/1b.md", 1, "email", "A job post put up again"),
    _T("1-two-roles", "touch1/1c.md", 1, "email", "Two roles posted at once"),
    _T("1-mass-tort", "touch1/1d.md", 1, "email", "A mass tort campaign"),
    _T("1-reviews", "touch1/1e.md", 1, "email", "Reviews about calls not returned"),
    _T("1-new-system", "touch1/1f.md", 1, "email", "A newly adopted case system"),
    _T("1-hourly", "touch1/tier4.md", 1, "email", "Every hourly firm (tier 4), whatever the pain"),
    _T("2-job-post", "touch2/base.md", 2, "email",
       "A job post: open, put up again, or two roles", keeps="specific_work_paragraph"),
    _T("2-paragraph-most", "touch2/_specific_work_1a.md", 2, "paragraph",
       "Its middle paragraph for every firm except immigration firms"),
    _T("2-paragraph-immigration", "touch2/_specific_work_1b.md", 2, "paragraph",
       "Its middle paragraph for immigration firms (tier 1B)"),
    _T("2-mass-tort", "touch2/pain_mass_tort.md", 2, "email", "A mass tort campaign"),
    _T("2-reviews", "touch2/pain_review.md", 2, "email", "Reviews about calls not returned"),
    _T("2-new-system", "touch2/pain_cms.md", 2, "email", "A newly adopted case system"),
    _T("3-contingency", "touch3/contingency.md", 3, "email", "Contingency firms"),
    _T("3-fee-shifting", "touch3/fee_shifting.md", 3, "email", "Fee-shifting firms"),
    _T("3-flat-fee", "touch3/flat_1b.md", 3, "email", "Flat-fee firms, except tier 3"),
    _T("3-flat-fee-volume", "touch3/flat_tier3.md", 3, "email", "Flat-fee volume firms (tier 3)"),
    _T("3-hourly", "touch3/hourly.md", 3, "email", "Hourly firms"),
    _T("4", "touch4.md", 4, "email", "Every firm"),
    _T("5", "touch5.md", 5, "email", "Every firm"),
    _T("6", "touch6.md", 6, "email", "Every firm"),
    _T("7", "touch7.md", 7, "email", "Every firm"),
    _T("8", "touch8.md", 8, "email", "While the job post is still up"),
    _T("9", "touch9.md", 9, "email", "Every firm"),
)

BY_ID: dict[str, CatalogueTemplate] = {t.id: t for t in TEMPLATES}
BY_PATH: dict[str, CatalogueTemplate] = {t.path: t for t in TEMPLATES}

# What a person may write in braces, in the order the editor offers them.
FILL_INS: dict[str, tuple[str, str]] = {
    "first_name": ("First name", "The decision-maker's first name."),
    "firm_name": ("Firm name", "The firm's name as it is on file."),
    "role": ("Job title", "The role in the firm's job post."),
    "role_2": ("Second job title", "The other role, when two are posted."),
    "posted_date": ("Date first seen", "The day we first saw the post: ours, not the job board's."),
    "repost_month": ("Repost month", "The month the post first went back up."),
    "days_open": ("Days open", "Days since we first saw the post."),
    "tort": ("Mass tort", "The campaign the firm is running intake for."),
    "practice": ("Practice area", "The firm's main practice."),
    "cms": ("Case system", "The firm's case management system."),
}
# Every lead has these, so any email may use them. Anything else only where
# the original used it: a fill-in a firm may lack would drop the lead.
ALWAYS_ALLOWED = ("first_name", "firm_name")
SLOTS = ("middle_paragraph", "specific_work_paragraph")

MAX_SUBJECT = 150
MAX_BODY = 3000
MAX_DAY = 90

_TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def tokens_in(text: str) -> list[str]:
    """Every `{name}` in `text`, first occurrence order, no repeats."""
    return list(dict.fromkeys(_TOKEN_RE.findall(text)))


def allowed_fill_ins(template: CatalogueTemplate) -> list[str]:
    """The fill-ins an edit of `template` may use, in the editor's order."""
    subject, body = load_template(template.path)
    used = set(tokens_in(f"{subject or ''}\n{body}"))
    return [name for name in FILL_INS if name in used or name in ALWAYS_ALLOWED]


def config_days() -> dict[int, int]:
    """Days after email 1, per email, as journey/sequences.yml sets them."""
    return {int(t["step"]): int(t["day"]) for t in load_config()["touches"]}


def schedule(days: Mapping[int, int]) -> dict[int, int]:
    """The original days with the screen's edits laid over them."""
    return {step: days.get(step, day) for step, day in config_days().items()}


def banned_in(text: str) -> list[str]:
    """The banned phrases (sequences.yml) in `text`: a case-blind substring
    match, as `select.scan_banned` does, returned as the phrases themselves."""
    lowered = text.lower()
    return [p for p in load_config()["banned_phrases"] if p.lower() in lowered]


def copy_problems(template: CatalogueTemplate, subject: str | None, body: str) -> list[str]:
    """Why an edit cannot be saved, in words; empty when it can."""
    problems: list[str] = []
    subject = subject or ""
    noun = "email" if template.kind == "email" else "paragraph"

    if template.kind == "email":
        if not subject.strip():
            problems.append("Add a subject line.")
        elif "\n" in subject or "\r" in subject:
            problems.append("Keep the subject on one line.")
        elif len(subject) > MAX_SUBJECT:
            problems.append(f"Keep the subject under {MAX_SUBJECT} characters.")
    elif subject.strip():
        problems.append("A paragraph has no subject line.")

    if not body.strip():
        problems.append(f"The {noun} can't be empty.")
    elif len(body) > MAX_BODY:
        problems.append(f"Keep the {noun} under {MAX_BODY:,} characters.")

    text = f"{subject}\n{body}"
    banned = banned_in(text)
    if banned:
        words = ", ".join(f"“{p}”" for p in banned)
        problems.append(
            f"It uses words these emails never use: {words}. They read as replacing "
            "someone's staff, and the email dies in that person's inbox."
        )

    allowed = set(allowed_fill_ins(template))
    slot = template.keeps
    unknown = [t for t in tokens_in(text) if t not in allowed and t != slot]
    if unknown:
        names = ", ".join(f"{{{t}}}" for t in unknown)
        can_use = ", ".join(f"{{{t}}}" for t in allowed_fill_ins(template))
        problems.append(f"{names} can't be filled in here. This {noun} can use {can_use}.")

    if "{" in _TOKEN_RE.sub("", text) or "}" in _TOKEN_RE.sub("", text):
        problems.append("A { or } that is not part of a fill-in would be sent as it is.")

    if slot is not None:
        if body.count(f"{{{slot}}}") != 1 or f"{{{slot}}}" in subject:
            problems.append(
                f"Keep {{{slot}}} in the body exactly once: the tier's paragraph goes there."
            )

    return problems


def day_problems(days: Mapping[int, int]) -> list[str]:
    """Why a new schedule cannot be saved, in words; empty when it can.
    `days` holds days after email 1, for any of emails 2 to 9."""
    problems: list[str] = []
    for step, day in sorted(days.items()):
        if step not in STEPS or step == 1:
            problems.append(
                "Email 1 always goes on Day 1." if step == 1 else f"There is no email {step}."
            )
        elif not 1 <= day <= MAX_DAY:
            problems.append(f"Email {step} must go between Day 2 and Day {MAX_DAY + 1}.")
    if problems:
        return problems

    full = schedule(days)
    for step in sorted(full)[1:]:
        if full[step] <= full[step - 1]:
            problems.append(
                f"Email {step} must come after email {step - 1}, "
                f"which goes on Day {full[step - 1] + 1}."
            )
    return problems
