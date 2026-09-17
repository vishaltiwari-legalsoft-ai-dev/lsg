"""config/crawl.yml's caps are the one list of what the engine reads (D-044)."""

from __future__ import annotations

from lge.fetch.config import (
    caps,
    crawl_into_kinds,
    kind_cap,
    kinds_version,
    only_wanted,
    wanted_kinds,
)


def test_wanted_kinds_are_the_positive_caps_in_config_order():
    wanted = wanted_kinds()
    assert wanted[0] == "home"
    assert set(wanted) == {
        "home", "contact", "about", "attorneys", "team", "careers", "testimonials"
    }
    for k in ("practice", "news", "locations", "fees", "other"):
        assert k not in wanted and kind_cap(k) == 0
    assert "total" not in wanted
    assert sum(kind_cap(k) for k in wanted) >= caps()["total"] == 12


def test_home_is_never_crawled_into():
    assert "home" not in crawl_into_kinds()
    assert set(crawl_into_kinds()) == set(wanted_kinds()) - {"home"}


def test_a_reader_keeps_its_own_order_minus_what_is_not_read():
    assert only_wanted(("practice", "fees", "home", "about", "other", "contact")) == (
        "home", "about", "contact"
    )
    assert only_wanted(()) == ()


def test_the_kinds_version_changes_when_the_list_does():
    assert kinds_version() == "kinds:" + ",".join(wanted_kinds())
