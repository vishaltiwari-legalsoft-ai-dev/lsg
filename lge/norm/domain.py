"""norm_domain / norm_email_domain — canonical registered-domain identity keys.

Bump NORM_VERSION["norm_domain"] whenever output can change for any input.

A domain (or an email's domain half) is only useful as an identity/join key if it
actually identifies one firm. Shared hosting platforms and free-mail providers fail
that test silently — dozens of unrelated firms share one Wix subdomain suffix or one
Gmail domain — so both are blocklisted rather than merely lowercased through.
"""

from __future__ import annotations

import ipaddress
import re
from functools import lru_cache
from urllib.parse import urlsplit

import tldextract

# The spec's six. Load-bearing: every firm on one of these merges into one entity if
# this list is wrong. See context/30-data-model/02-normalization-contracts.md.
_SPEC_SHARED_HOSTS = frozenset(
    {
        "wixsite.com",
        "squarespace.com",
        "godaddysites.com",
        "justia.com",
        "avvo.com",
        "findlaw.com",
    }
)

# Extension beyond the spec's six: other shared-hosting platforms, legal-directory
# aggregators, and social/search platforms a firm's "website" field sometimes holds
# instead of (or alongside) its real site. Kept as a separate constant so the spec's
# original list stays visible above.
_SHARED_HOST_EXTENSIONS = frozenset(
    {
        "wordpress.com",
        "weebly.com",
        "blogspot.com",
        "business.site",
        "mystrikingly.com",
        "webs.com",
        "jimdosite.com",
        "square.site",
        "lawyers.com",
        "martindale.com",
        "nolo.com",
        "superlawyers.com",
        "facebook.com",
        "linkedin.com",
        "yelp.com",
        "google.com",
        "youtube.com",
        "instagram.com",
        "x.com",
        "twitter.com",
    }
)

SHARED_HOST_BLOCKLIST: frozenset[str] = _SPEC_SHARED_HOSTS | _SHARED_HOST_EXTENSIONS

# A firm using a free-mail address has no domain identity in that email at all.
FREEMAIL_BLOCKLIST: frozenset[str] = frozenset(
    {
        "gmail.com",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "aol.com",
        "icloud.com",
        "me.com",
        "msn.com",
        "live.com",
        "comcast.net",
        "att.net",
        "sbcglobal.net",
        "verizon.net",
        "protonmail.com",
        "proton.me",
        "ymail.com",
        "mail.com",
        "gmx.com",
        "zoho.com",
        "bellsouth.net",
        "cox.net",
        "charter.net",
        "earthlink.net",
    }
)

_STRIP_SUBDOMAIN_LABELS = frozenset({"www", "m", "amp"})
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


@lru_cache(maxsize=1)
def _extractor() -> tldextract.TLDExtract:
    # Offline snapshot only — this must never hit the network, in tests or in prod.
    return tldextract.TLDExtract(suffix_list_urls=())


def _is_ip_literal(host: str) -> bool:
    candidate = host.strip("[]")
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return False
    return True


def _extract_host(value: str) -> str | None:
    v = value.strip()
    if not v:
        return None
    if not _SCHEME_RE.match(v):
        # Bare host, host:port, or host/path — give urlsplit a scheme so it parses
        # netloc correctly instead of treating the whole thing as a path.
        v = "//" + v.lstrip("/")
    parts = urlsplit(v)
    host = parts.netloc or parts.path
    if not host:
        return None
    # Drop userinfo (user:pass@) and port.
    host = host.rsplit("@", 1)[-1]
    if host.startswith("["):
        # IPv6 literal — keep the bracket form for the IP check, strip for the rest.
        end = host.find("]")
        if end != -1:
            return host[: end + 1]
    host = host.split(":", 1)[0]
    host = host.strip(". \t")
    return host or None


def norm_domain(value: str | None) -> str | None:
    """URL, bare host, or scheme-relative string -> lowercase eTLD+1, or None.

    None is returned for: empty input, an IP literal, a host with no valid public
    suffix, and any registered domain in SHARED_HOST_BLOCKLIST.
    """
    if not value:
        return None
    host = _extract_host(value.lower())
    if not host:
        return None
    if _is_ip_literal(host):
        return None
    # Reducing to eTLD+1 already discards any leading www./m./amp. (and every other
    # subdomain label) since those live in ext.subdomain, never in ext.domain.
    ext = _extractor()(host)
    if not ext.suffix or not ext.domain:
        return None
    registered = f"{ext.domain}.{ext.suffix}"
    if registered in SHARED_HOST_BLOCKLIST:
        return None
    return registered


def norm_email_domain(email: str | None) -> str | None:
    """Email -> its normalized domain, or None (free-mail providers included)."""
    if not email or "@" not in email:
        return None
    _local, _, domain_part = email.strip().rpartition("@")
    if not domain_part:
        return None
    result = norm_domain(domain_part)
    if result is None or result in FREEMAIL_BLOCKLIST:
        return None
    return result
