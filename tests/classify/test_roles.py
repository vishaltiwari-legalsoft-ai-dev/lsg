from lge.classify.roles import classify_role


def test_owner_strong_titles():
    for title in [
        "Owner",
        "Founder",
        "Founding Partner",
        "Founding Attorney",
        "Managing Partner",
        "Managing Attorney",
        "Managing Member",
        "Principal Attorney",
        "Principal",
        "President",
        "CEO",
        "Name Partner",
        "Senior Partner",
        "Shareholder",
    ]:
        result = classify_role(title)
        assert result.role == "owner", f"{title!r} -> {result.role}"
        assert result.confidence == 0.9


def test_managing_attorney_is_owner_not_attorney():
    result = classify_role("Managing Attorney")
    assert result.role == "owner"
    assert result.confidence == 0.9


def test_plain_partner_is_owner_weak():
    result = classify_role("Partner")
    assert result.role == "owner"
    assert result.confidence == 0.6


def test_attorney_slash_partner_is_owner_weak():
    result = classify_role("Attorney/Partner")
    assert result.role == "owner"
    assert result.confidence == 0.6

    result2 = classify_role("Partner / Attorney")
    assert result2.role == "owner"
    assert result2.confidence == 0.6


def test_admin_titles():
    for title in [
        "Office Manager",
        "Firm Administrator",
        "Legal Administrator",
        "Director of Operations",
        "Operations Manager",
        "Operations Director",
        "Practice Manager",
        "Chief Operating Officer",
        "COO",
        "Executive Director",
        "Firm Manager",
        "Business Manager",
        "Director of Administration",
    ]:
        result = classify_role(title)
        assert result.role == "admin", f"{title!r} -> {result.role}"
        assert result.confidence == 0.9


def test_attorney_titles():
    for title in [
        "Attorney",
        "Associate",
        "Lawyer",
        "Of Counsel",
        "Counsel",
        "Staff Attorney",
        "Trial Attorney",
        "Litigation Attorney",
        "Senior Attorney",
        "Immigration Attorney",
        "Patent Attorney",
        "Attorney At Law",
    ]:
        result = classify_role(title)
        assert result.role == "attorney", f"{title!r} -> {result.role}"
        assert result.confidence == 0.9


def test_unrecognized_title_is_unknown():
    result = classify_role("Marketing Coordinator")
    assert result.role == "unknown"
    assert result.confidence == 0.0


def test_empty_and_none_title():
    assert classify_role(None) == classify_role("")
    assert classify_role(None).role == "unknown"
    assert classify_role(None).confidence == 0.0


def test_case_insensitive_and_punctuation_tolerant():
    result = classify_role("OFFICE MANAGER, ESQ.")
    assert result.role == "admin"

    result2 = classify_role("managing partner,")
    assert result2.role == "owner"
    assert result2.confidence == 0.9


def test_precedence_owner_and_admin_before_attorney():
    # A title that could plausibly read as attorney-ish but is explicitly an owner
    # title must resolve to owner, never attorney.
    result = classify_role("Managing Attorney and Founder")
    assert result.role == "owner"
    assert result.confidence == 0.9
