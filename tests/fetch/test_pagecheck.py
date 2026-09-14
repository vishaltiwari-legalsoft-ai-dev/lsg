"""looks_like_soft_404 / looks_like_js_shell: what a fetched page is."""

from __future__ import annotations

from lge.fetch.pagecheck import looks_like_js_shell, looks_like_soft_404, visible_words

ARTICLE = "<html><body><h1>Truck accidents</h1>" + "<p>word</p>" * 300 + "</body></html>"
NOT_FOUND = "<html><body><h1>Page not found</h1><p>Try the menu.</p></body></html>"
OOPS = "<html><body><h2>Oops! That page could not be found</h2></body></html>"
SHELL = (
    '<html><body><div id="root"></div><script src="/a.js"></script>'
    "<script>window.__NEXT_DATA__={}</script></body></html>"
)
THIN_STATIC = "<html><body><h1>Contact</h1><p>Call us at 555-0100.</p></body></html>"


def test_soft_404_is_a_short_error_page_only():
    assert looks_like_soft_404(NOT_FOUND)
    assert looks_like_soft_404(OOPS)
    assert not looks_like_soft_404(ARTICLE.replace("<h1>", "<h1>error 404 "))  # long article
    assert not looks_like_soft_404("")


def test_js_shell_is_empty_text_with_a_root_or_many_scripts():
    assert looks_like_js_shell(SHELL)
    many_scripts = (
        "<html><body><p>Loading</p>" + '<script src="x.js"></script>' * 3 + "</body></html>"
    )
    assert looks_like_js_shell(many_scripts)
    assert not looks_like_js_shell(ARTICLE)  # plenty of text, nothing to render
    assert not looks_like_js_shell(THIN_STATIC)  # thin, but not a shell
    assert visible_words(THIN_STATIC) == 5  # "Contact" + "Call us at 555-0100."
