"""Token resolution rules: plan/outreach-journey.md's "Personalization
tokens -> columns" table, transcribed as tests. No DB -- every function
here is pure.
"""

from __future__ import annotations

from datetime import date, datetime

from lge.journey.tokens import (
    days_open,
    format_month_name,
    format_posted_date,
    humanize_cms,
    humanize_practice,
    humanize_role,
    resolve_first_name,
    role_from_evidence,
    tort_from_evidence,
)


class TestResolveFirstName:
    def test_plain_first_last(self):
        assert resolve_first_name("John Smith") == "John"

    def test_honorific_prefix_dr(self):
        assert resolve_first_name("Dr. John Smith") == "John"

    def test_honorific_prefix_mr(self):
        assert resolve_first_name("Mr. John Smith") == "John"

    def test_comma_last_first_format(self):
        assert resolve_first_name("Smith, John") == "John"

    def test_comma_last_first_middle(self):
        assert resolve_first_name("Smith, John Q.") == "John"

    def test_comma_format_with_title_after_comma(self):
        assert resolve_first_name("Smith, Dr. John") == "John"

    def test_honorific_plus_surname_only_is_unresolved(self):
        # "Mr. Smith" is a surname-only record -- the first name is
        # genuinely unknown, so this must NOT resolve to "Smith".
        assert resolve_first_name("Mr. Smith") is None

    def test_missing_name_is_unresolved(self):
        assert resolve_first_name(None) is None
        assert resolve_first_name("") is None
        assert resolve_first_name("   ") is None

    def test_extra_whitespace_normalised(self):
        assert resolve_first_name("  John   Smith  ") == "John"


class TestHumanizeRole:
    def test_underscore_to_space(self):
        assert humanize_role("demand_writer") == "demand writer"
        assert humanize_role("document_collector") == "document collector"
        assert humanize_role("paralegal") == "paralegal"
        assert humanize_role("legal_assistant") == "legal assistant"

    def test_none_and_empty(self):
        assert humanize_role(None) is None
        assert humanize_role("") is None


class TestRoleFromEvidence:
    def test_prefers_canonical_role(self):
        evidence = {"title": "PI Paralegal - Full Time", "canonical_role": "paralegal"}
        assert role_from_evidence(evidence) == "paralegal"

    def test_falls_back_to_title_when_canonical_role_missing(self):
        evidence = {"title": "Legal Ninja"}
        assert role_from_evidence(evidence) == "Legal Ninja"

    def test_falls_back_to_title_when_canonical_role_empty(self):
        evidence = {"title": "Legal Ninja", "canonical_role": None}
        assert role_from_evidence(evidence) == "Legal Ninja"

    def test_empty_evidence_unresolved(self):
        assert role_from_evidence({}) is None
        assert role_from_evidence(None) is None


class TestHumanizePractice:
    def test_known_slugs(self):
        assert humanize_practice("personal_injury") == "personal injury"
        assert humanize_practice("workers_comp") == "workers compensation"
        assert humanize_practice("ssdi") == "SSDI"
        assert humanize_practice("immigration") == "immigration"

    def test_unknown_slug_falls_back_to_replace(self):
        assert humanize_practice("some_new_slug") == "some new slug"

    def test_none(self):
        assert humanize_practice(None) is None


class TestHumanizeCms:
    def test_known_vendors(self):
        assert humanize_cms("filevine") == "Filevine"
        assert humanize_cms("clio") == "Clio"
        assert humanize_cms("casepeer") == "CASEpeer"
        assert humanize_cms("mycase") == "MyCase"
        assert humanize_cms("smartadvocate") == "SmartAdvocate"
        assert humanize_cms("litify") == "Litify"

    def test_unknown_vendor_falls_back_to_capitalize(self):
        assert humanize_cms("somenewcms") == "Somenewcms"

    def test_none(self):
        assert humanize_cms(None) is None


class TestDatesAndDurations:
    def test_format_posted_date(self):
        assert format_posted_date(datetime(2026, 8, 14)) == "14 August"

    def test_format_posted_date_single_digit_day_no_leading_zero(self):
        assert format_posted_date(datetime(2026, 8, 4)) == "4 August"

    def test_format_month_name(self):
        assert format_month_name(date(2026, 3, 17)) == "March"

    def test_days_open(self):
        assert days_open(datetime(2026, 8, 1), datetime(2026, 9, 11)) == "41"

    def test_days_open_none_first_seen(self):
        assert days_open(None, datetime(2026, 9, 11)) is None


class TestTortFromEvidence:
    def test_prefers_tort_field(self):
        assert tort_from_evidence({"tort": "Camp Lejeune"}) == "Camp Lejeune"

    def test_falls_back_to_title(self):
        assert tort_from_evidence({"title": "Roundup intake"}) == "Roundup intake"

    def test_empty(self):
        assert tort_from_evidence({}) is None
        assert tort_from_evidence(None) is None
