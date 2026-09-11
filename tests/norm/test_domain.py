from lge.norm import NORM_VERSION
from lge.norm.domain import SHARED_HOST_BLOCKLIST, norm_domain, norm_email_domain


def test_shared_host_never_becomes_a_key():
    assert norm_domain("https://smithlaw.wixsite.com/home") is None
    assert norm_domain("https://smithlaw.squarespace.com") is None
    assert norm_domain("https://smithlaw.godaddysites.com/home") is None
    assert norm_domain("https://www.justia.com/lawyers/smith") is None
    assert norm_domain("https://www.avvo.com/attorneys/smith") is None
    assert norm_domain("https://www.findlaw.com/profile/smith") is None


def test_shared_host_extensions_also_blocked():
    assert norm_domain("https://smithlaw.wordpress.com") is None
    assert norm_domain("https://smithlaw.weebly.com") is None
    assert norm_domain("https://www.facebook.com/smithlaw") is None
    assert norm_domain("https://www.linkedin.com/company/smithlaw") is None
    assert norm_domain("https://smithlaw.business.site") is None


def test_scheme_www_path_port_case_variants_collapse_to_one_value():
    variants = [
        "https://www.SmithLaw.com/contact",
        "http://smithlaw.com",
        "smithlaw.com",
        "SMITHLAW.COM",
        "m.smithlaw.com",
        "amp.smithlaw.com/blog/post",
        "www.smithlaw.com:8443/path?x=1",
        "https://smithlaw.com/",
    ]
    results = {norm_domain(v) for v in variants}
    assert results == {"smithlaw.com"}


def test_multipart_suffix_resolves_to_registered_domain():
    # "co.uk" is a public suffix; the registrable name sits one level below it.
    assert norm_domain("smith.law.co.uk") == "law.co.uk"
    assert norm_domain("https://www.smith.law.co.uk/contact") == "law.co.uk"
    # "com.au" likewise.
    assert norm_domain("firm.com.au") == "firm.com.au"
    assert norm_domain("https://www.firm.com.au") == "firm.com.au"


def test_ip_addresses_are_not_domains():
    assert norm_domain("192.168.1.1") is None
    assert norm_domain("http://8.8.8.8/") is None
    assert norm_domain("http://[::1]/") is None


def test_empty_and_none_input():
    assert norm_domain(None) is None
    assert norm_domain("") is None
    assert norm_domain("   ") is None


def test_no_valid_suffix_returns_none():
    assert norm_domain("localhost") is None
    assert norm_domain("http://intranet/") is None


def test_norm_email_domain_freemail_blocked():
    assert norm_email_domain("partner@gmail.com") is None
    assert norm_email_domain("info@Yahoo.com") is None
    assert norm_email_domain("hello@ProtonMail.com") is None
    assert norm_email_domain("x@comcast.net") is None


def test_norm_email_domain_firm_domain_passes_through():
    assert norm_email_domain("info@SmithLaw.com") == "smithlaw.com"
    assert norm_email_domain("partner@www.smithlaw.com") == "smithlaw.com"


def test_norm_email_domain_shared_host_blocked():
    assert norm_email_domain("info@smithlaw.wixsite.com") is None


def test_norm_email_domain_malformed_input():
    assert norm_email_domain(None) is None
    assert norm_email_domain("not-an-email") is None
    assert norm_email_domain("missing-domain@") is None


def test_blocklist_contains_spec_six():
    for host in (
        "wixsite.com",
        "squarespace.com",
        "godaddysites.com",
        "justia.com",
        "avvo.com",
        "findlaw.com",
    ):
        assert host in SHARED_HOST_BLOCKLIST


def test_norm_version_present():
    assert NORM_VERSION["norm_domain"] == "1"
