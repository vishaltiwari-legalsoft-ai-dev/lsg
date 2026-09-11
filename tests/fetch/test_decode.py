"""decode_html — found live: "You won’t pay…" stored as "You won�t pay…"."""

from lge.fetch.decode import decode_html

CURLY = "You won’t pay anything unless you win"


def test_windows_1252_page_is_not_mangled():
    body = f"<html><body><p>{CURLY}</p></body></html>".encode("cp1252")
    text = decode_html(body)
    assert CURLY in text
    assert "�" not in text


def test_utf8_page_round_trips():
    body = f"<html><head><meta charset='utf-8'></head><body>{CURLY}</body></html>".encode()
    assert CURLY in decode_html(body)


def test_declared_charset_wins_when_it_decodes():
    body = (b'<html><head><meta http-equiv="Content-Type" content="text/html; '
            b'charset=windows-1252"></head><body>' + CURLY.encode("cp1252") + b"</body></html>")
    assert CURLY in decode_html(body)


def test_lying_declared_charset_falls_back():
    # declares utf-8 but is actually cp1252 — strict utf-8 fails, cp1252 succeeds
    body = b"<meta charset='utf-8'><p>" + CURLY.encode("cp1252") + b"</p>"
    assert CURLY in decode_html(body)


def test_bom_is_honoured_and_stripped():
    body = b"\xef\xbb\xbf<p>" + CURLY.encode("utf-8") + b"</p>"
    text = decode_html(body)
    assert text.startswith("<p>")
    assert CURLY in text


def test_empty_is_empty():
    assert decode_html(b"") == ""
    assert decode_html(None) == ""
