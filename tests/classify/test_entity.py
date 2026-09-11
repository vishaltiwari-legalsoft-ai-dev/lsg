import pytest

from lge.classify.entity import classify_entity


@pytest.mark.parametrize(
    ("name", "domain", "kind"),
    [
        # the real offenders from the purchased vendor file
        ("U.S. Department of Justice", "usdoj.gov", "gov"),
        ("Orleans Parish District Attorney's Office", "orleansda.com", "gov"),
        ("Legal Aid of NorthWest Texas", "lanwt.org", "nonprofit"),
        ("Center for Arkansas Legal Services", "arlegalaid.org", "nonprofit"),
        ("Oakland University", "oakland.edu", "inhouse"),
        # other government forms
        ("Office of the Public Defender", "opd.example.com", "gov"),
        ("Cook County State's Attorney", "cookcountysao.org", "gov"),
        ("Anything", "courts.state.ny.us", "gov"),
        ("Anything", "army.mil", "gov"),
        # non-profit via .org + 'legal services'
        ("Neighborhood Legal Services", "nls.org", "nonprofit"),
        ("Volunteer Lawyers Network", "vln.example.net", "nonprofit"),
        ("Georgetown University Law Center", "law.example.com", "inhouse"),
    ],
)
def test_non_private_entities(name, domain, kind):
    assert classify_entity(name, domain).kind == kind


@pytest.mark.parametrize(
    ("name", "domain"),
    [
        ("Smith Legal Services", "smithlegal.com"),       # private firm, .com
        ("Garcia Immigration Law Group", "garcialaw.com"),
        ("Justice Law Firm", "justicelaw.com"),            # 'justice' alone is not a rule
        ("Johnson & Associates PLLC", "johnsonpllc.com"),
    ],
)
def test_private_firms_get_no_verdict(name, domain):
    # absence of evidence is not a verdict — no claim, not "private_firm"
    result = classify_entity(name, domain)
    assert result.kind is None
    assert result.confidence == 0.0


def test_government_outranks_nonprofit():
    assert classify_entity("Legal Aid Bureau", "example.gov").kind == "gov"


def test_evidence_names_the_rule():
    r = classify_entity("Orleans Parish District Attorney", "orleansda.com")
    assert "district attorney" in r.evidence.lower()
