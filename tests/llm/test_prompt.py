"""select_and_trim / build_user_message / build_system_prompt
(context/40-pipeline/03-extraction-contract.md: page order, the char
budget, and "trim practice/home first, never attorneys/team first")."""

from __future__ import annotations

from lge.llm.prompt import PageDoc, build_system_prompt, build_user_message, select_and_trim
from lge.llm.schema import practice_area_slugs


def _page(kind: str, url: str, words: str, n: int) -> PageDoc:
    return PageDoc(page_kind=kind, url=url, main_text=(words + " ") * n)


def test_build_system_prompt_lists_every_practice_slug():
    prompt = build_system_prompt()
    for slug in practice_area_slugs():
        assert slug in prompt


def test_build_system_prompt_covers_fee_model_families_and_unknown_rule():
    prompt = build_system_prompt().lower()
    for term in ("contingency", "fee_shifting", "flat", "hourly", "mixed", "unknown"):
        assert term in prompt
    assert "never estimate" in prompt or "never guess" in prompt


def test_within_budget_keeps_every_page_in_display_order():
    pages = [
        _page("contact", "http://x/contact", "c", 5),
        _page("home", "http://x/", "h", 5),
        _page("attorneys", "http://x/attorneys", "a", 5),
        _page("about", "http://x/about", "ab", 5),
    ]
    selected = select_and_trim(pages, char_budget=10_000)
    assert [p.page_kind for p in selected] == ["home", "about", "attorneys", "contact"]


def test_practice_pages_capped_at_three_longest_first():
    pages = [
        _page("practice", "http://x/p1", "short", 5),
        _page("practice", "http://x/p2", "longest", 500),
        _page("practice", "http://x/p3", "mid", 100),
        _page("practice", "http://x/p4", "mid2", 50),
        _page("practice", "http://x/p5", "shortest", 1),
    ]
    selected = select_and_trim(pages, char_budget=100_000)
    assert len(selected) == 3
    lengths = [len(p.main_text) for p in selected]
    assert lengths == sorted(lengths, reverse=True)
    assert {p.url for p in selected} == {"http://x/p2", "http://x/p3", "http://x/p4"}


def test_over_budget_drops_home_and_practice_before_attorneys_and_team():
    pages = [
        _page("home", "http://x/", "h", 2000),
        _page("practice", "http://x/p", "p", 2000),
        _page("attorneys", "http://x/attorneys", "a", 2000),
        _page("team", "http://x/team", "t", 2000),
    ]
    selected = select_and_trim(pages, char_budget=8_000)
    kinds = {p.page_kind for p in selected}
    assert "attorneys" in kinds
    assert "team" in kinds
    # home/practice are the ones sacrificed when the budget is tight.
    assert "home" not in kinds or "practice" not in kinds


def test_attorneys_and_team_never_dropped_even_far_over_budget():
    pages = [
        _page("home", "http://x/", "h", 50),
        _page("attorneys", "http://x/attorneys", "a", 5000),
        _page("team", "http://x/team", "t", 5000),
    ]
    selected = select_and_trim(pages, char_budget=100)
    kinds = {p.page_kind for p in selected}
    assert "attorneys" in kinds
    assert "team" in kinds


def test_build_user_message_formats_blocks_with_kind_and_url():
    pages = [_page("home", "http://example.com/", "hello world", 3)]
    message = build_user_message(pages)
    assert message.startswith("### home — http://example.com/")
    assert "hello world" in message
