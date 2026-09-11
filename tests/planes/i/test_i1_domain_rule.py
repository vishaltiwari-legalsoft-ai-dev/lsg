"""The email-domain fallback may only key a firm when it visibly belongs to it."""

import pytest

from lge.norm import norm_name
from lge.planes.i.i1_firms import _email_domain_plausible, _resolve_domain


@pytest.mark.parametrize(
    ("firm_name", "email_domain"),
    [
        # real mismatches from the purchased file — each would have merged or
        # mis-keyed a firm if accepted
        ("Faggiano & Associates", "adlercohen.com"),
        ("Bernice Lake Pc", "mattel.com"),
        ("Apricity Law", "meketa.com"),
        ("Burns Legal Group Pllc", "continuumhealthtech.com"),
        ("Gursky Wiens Attorneys At Law Ltd", "umd.edu"),
        ("Meyer & Downs", "kearsarge.org"),
    ],
)
def test_foreign_email_domains_rejected(firm_name, email_domain):
    assert not _email_domain_plausible(email_domain, norm_name(firm_name))


@pytest.mark.parametrize(
    ("firm_name", "email_domain"),
    [
        ("Estefano Law P.A.", "estefanolaw.com"),
        ("Khurana Law Firm Pc", "khuranalegal.com"),
        ("Burke Rosen & Associates", "burkerosen.com"),
        ("Brinson Askew Berry", "brinson-askew.com"),
        ("Hines Hampton Pelanda", "hineshamptonllp.com"),
        ("Joyce And Associates", "joyceassociates.com"),
        ("Gavrilovich Dodd & Lindsey", "gdllawfirm.com"),  # initials
    ],
)
def test_own_email_domains_accepted(firm_name, email_domain):
    assert _email_domain_plausible(email_domain, norm_name(firm_name))


def test_company_url_always_wins_over_email():
    domain, from_email = _resolve_domain("https://www.smithlaw.com/", "a@other.com", "smith")
    assert (domain, from_email) == ("smithlaw.com", False)


def test_shared_host_url_falls_back_only_to_a_plausible_email():
    stem = norm_name("Burke Rosen & Associates")
    assert _resolve_domain("burkerosen.wixsite.com", "jo@burkerosen.com", stem) == (
        "burkerosen.com",
        True,
    )
    assert _resolve_domain("burkerosen.wixsite.com", "jo@mattel.com", stem) == (None, False)
