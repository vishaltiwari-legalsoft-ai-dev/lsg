"""The first/last split that every address scheme is rendered from: suffixes
and the comma form must not leak into an address (28 Sep 2026 live run:
"John A. Smith Jr." produced john.jr@)."""

import pytest

from lge.planes.r.r3_email_pattern import _name_parts, render_pattern
from lge.planes.r.r_email_guess import candidates


@pytest.mark.parametrize(
    ("full_name", "expected"),
    [
        ("John Smith", ("john", "smith")),
        ("John A. Smith", ("john", "smith")),
        ("John A. Smith Jr.", ("john", "smith")),
        ("Rosalind Fuchsberg Kaufman, Esq.", ("rosalind", "kaufman")),
        ("Smith, John A.", ("john", "smith")),
        ("Anthony Simari III", ("anthony", "simari")),
        ("Dr. Jane O'Neil-Ross", ("dr", "oneilross")),
        ("Madonna", None),
        ("Smith Jr.", None),
        ("", None),
        (None, None),
    ],
)
def test_name_parts(full_name, expected):
    assert _name_parts(full_name) == expected


def test_render_and_candidates_use_the_cleaned_name():
    assert render_pattern("John A. Smith Jr.", "first.last") == "john.smith"
    addresses = [a for _, a in candidates("Smith, John A.", "example.com")]
    assert addresses[0] == "john.smith@example.com"
    assert "jr" not in "".join(addresses)
