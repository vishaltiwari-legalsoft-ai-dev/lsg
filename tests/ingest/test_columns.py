"""The ColumnReader seam: the AI's reading is adopted where the values agree,
overruled where they do not, rescued by the rules where it was unsure, and
replaced by the rules entirely when the model cannot be reached. Which
reader runs is the settings' choice. No test here calls out."""

from __future__ import annotations

from pathlib import Path

import pytest

from lge.ingest.columns import (
    LLMColumnReader,
    RuleColumnReader,
    get_column_reader,
    read_columns,
)
from lge.llm.sheet_reader import ColumnRead, SheetRead, build_user_message
from lge.settings import COLUMN_READERS, Settings, _choice

HEADERS = ["Firm", "Site", "Who", "Role", "Reach", "Hdc"]
ROWS = [
    {"Firm": "Acme Injury Law", "Site": "acme.law", "Who": "Jane Doe", "Role": "Owner",
     "Reach": "jane@acme.law", "Hdc": "4"},
    {"Firm": "Beta Legal", "Site": "beta.law", "Who": "Bob Roe", "Role": "Office Manager",
     "Reach": "bob@beta.law", "Hdc": "12"},
    {"Firm": "Gamma LLP", "Site": "gamma.com", "Who": "Ann Lee", "Role": "Partner",
     "Reach": "ann@gamma.com", "Hdc": "2"},
]


def _settings(**over) -> Settings:
    base = dict(
        dsn="", admin_dsn="", object_store=Path("."), user_agent="", anthropic_api_key="",
        openrouter_api_key="", live=False, column_reader="auto", search_engine="auto",
        serper_api_key="", brave_api_key="", email_finder="auto", email_verifier="auto",
        hunter_api_key="", neverbounce_api_key="",
    )
    base.update(over)
    return Settings(**base)


def _sheet(*cols: tuple[str, str | None, float, str], notes: list[str] | None = None) -> SheetRead:
    return SheetRead(
        columns=[ColumnRead(column=c, field=f, confidence=k, reason=r) for c, f, k, r in cols],
        notes=notes or [],
    )


def _fake(sheet: SheetRead):
    calls: list[dict] = []

    def call(headers, rows, *, api_key):
        calls.append({"headers": headers, "rows": rows, "api_key": api_key})
        return sheet

    return call, calls


def test_the_ai_reading_is_adopted_where_the_rules_could_not_tell():
    sheet = _sheet(
        ("Firm", "firm_name", 0.98, "the firm's name"),
        ("Site", "website", 0.97, "web addresses"),
        ("Who", "person_name", 0.9, "personal names beside a role"),
        ("Role", "person_title", 0.9, "job titles"),
        ("Reach", "email", 0.95, "email addresses"),
        ("Hdc", "firm_size", 0.8, "attorney headcount"),
        notes=["no location column"],
    )
    call, calls = _fake(sheet)
    cm = LLMColumnReader("k", call=call).read(HEADERS, ROWS)
    assert calls[0]["api_key"] == "k" and calls[0]["headers"] == HEADERS
    assert cm.reader == "llm"
    assert cm.mapping["person_name"] == "Who" and cm.mapping["person_title"] == "Role"
    assert cm.mapping["email"] == "Reach" and cm.mapping["firm_size"] == "Hdc"
    assert cm.missing == [] and "location" in cm.research_fills
    assert cm.notes == ["no location column"]
    who = next(g for g in cm.guesses if g.column == "Who")
    assert who.reason.startswith("AI:") and who.confidence == 0.9


def test_a_typed_field_the_values_contradict_is_not_adopted():
    # the AI calls the website column an email column; the cells are URLs
    sheet = _sheet(
        ("Firm", "firm_name", 0.98, "name"), ("Site", "email", 0.9, "addresses"),
        ("Who", None, 0.0, ""), ("Role", None, 0.0, ""), ("Reach", "email", 0.95, "addresses"),
        ("Hdc", None, 0.0, ""),
    )
    call, _ = _fake(sheet)
    cm = LLMColumnReader("k", call=call).read(HEADERS, ROWS)
    assert cm.mapping["website"] == "Site" and cm.mapping["email"] == "Reach"
    site = next(g for g in cm.guesses if g.column == "Site")
    assert "AI said Email, the values do not look like it" in site.reason


def test_a_column_the_ai_left_null_is_rescued_by_a_sure_rule():
    headers = ["Company Name", "Business Email"]
    rows = [{"Company Name": f"Firm {i}", "Business Email": f"p{i}@firm{i}.com"} for i in range(4)]
    sheet = _sheet(("Company Name", None, 0.3, "unclear"), ("Business Email", None, 0.2, "unclear"))
    call, _ = _fake(sheet)
    cm = LLMColumnReader("k", call=call).read(headers, rows)
    assert cm.mapping["firm_name"] == "Company Name" and cm.mapping["email"] == "Business Email"
    g = next(g for g in cm.guesses if g.column == "Company Name")
    assert g.reason.startswith("AI: unclear;")


def test_an_unknown_field_name_from_the_ai_is_ignored_and_noted():
    sheet = _sheet(
        ("Firm", "company", 0.9, "made-up field"), ("Site", "website", 0.9, "urls"),
        ("Who", None, 0, ""), ("Role", None, 0, ""), ("Reach", "email", 0.9, ""),
        ("Hdc", None, 0, ""),
    )
    call, _ = _fake(sheet)
    cm = LLMColumnReader("k", call=call).read(HEADERS, ROWS)
    assert cm.mapping["firm_name"] == "Firm"  # the rules' "firm" synonym rescues it
    assert any("unknown field 'company'" in n for n in cm.notes)


def test_when_the_model_cannot_be_reached_the_rules_read_the_sheet():
    def call(headers, rows, *, api_key):
        raise ConnectionError("no route to host")

    cm = LLMColumnReader("k", call=call).read(HEADERS, ROWS)
    assert cm.reader == "rules"
    assert cm.mapping["firm_name"] == "Firm" and cm.mapping["website"] == "Site"
    assert any("AI reader was unavailable (ConnectionError)" in n for n in cm.notes)


def test_the_settings_choose_the_reader():
    assert isinstance(get_column_reader(_settings()), RuleColumnReader)
    assert isinstance(get_column_reader(_settings(openrouter_api_key="k")), LLMColumnReader)
    assert isinstance(get_column_reader(_settings(openrouter_api_key="k", column_reader="rules")),
                      RuleColumnReader)
    with pytest.raises(ValueError):  # an unknown name is refused when settings load
        _choice("magic", COLUMN_READERS, "LGE_COLUMN_READER")
    cm = read_columns(HEADERS, ROWS, _settings())
    assert cm.reader == "rules" and cm.mapping["firm_name"] == "Firm"


def test_the_user_message_is_small_and_aligned_to_the_headers():
    long_cell = {"Firm": "x" * 500, "Site": "s.com"}
    msg = build_user_message(["Firm", "Site"], [long_cell] * 30, limit=12)
    assert msg.count("s.com") == 12  # the sample is capped
    assert "x" * 61 not in msg  # and so is every cell
