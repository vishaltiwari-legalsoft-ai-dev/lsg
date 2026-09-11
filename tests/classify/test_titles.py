from lge.classify.titles import is_support_role, normalize_title


def test_seniority_employment_and_location_stripped():
    result = normalize_title("Sr. Litigation Paralegal - Full Time (Denver, CO)")
    assert result == "paralegal"


def test_paralegal_legal_assistant_first_canonical_by_order():
    # "paralegal" appears leftmost in the cleaned text, so it wins over the
    # "legal assistant" phrase that follows the slash.
    result = normalize_title("Paralegal/Legal Assistant")
    assert result == "paralegal"


def test_associate_attorney_is_attorney_not_support():
    result = normalize_title("Associate Attorney")
    assert result == "attorney"
    assert is_support_role(result) is False


def test_client_intake_specialist():
    result = normalize_title("Client Intake Specialist")
    assert result == "intake_specialist"
    assert is_support_role(result) is True


def test_case_manager():
    assert normalize_title("Case Manager") == "case_manager"
    assert normalize_title("Case Coordinator") == "case_manager"


def test_document_collector_synonyms():
    assert normalize_title("Records Clerk") == "document_collector"
    assert normalize_title("Medical Records Specialist") == "document_collector"


def test_legal_receptionist():
    assert normalize_title("Legal Receptionist") == "legal_receptionist"
    assert normalize_title("Receptionist (Part Time)") == "legal_receptionist"


def test_demand_writer_and_lien_negotiator():
    assert normalize_title("Demand Writer") == "demand_writer"
    assert normalize_title("Lien Negotiator") == "lien_negotiator"


def test_bookkeeper_synonyms():
    assert normalize_title("Bookkeeper") == "bookkeeper"
    assert normalize_title("Legal Bookkeeper") == "bookkeeper"
    assert normalize_title("Accounting Clerk") == "bookkeeper"


def test_seniority_tokens_stripped():
    assert normalize_title("Jr. Paralegal") == "paralegal"
    assert normalize_title("Paralegal II") == "paralegal"
    assert normalize_title("Lead Paralegal") == "paralegal"


def test_employment_terms_stripped():
    assert normalize_title("Paralegal (Part-Time)") == "paralegal"
    assert normalize_title("Contract Paralegal") == "paralegal"


def test_trailing_city_state_stripped():
    result = normalize_title("Legal Assistant, Springfield, IL")
    assert result == "legal_assistant"


def test_firm_name_stripped_when_given():
    result = normalize_title("Legal Assistant at Smith Law", firm_name="Smith Law")
    assert result == "legal_assistant"


def test_no_synonym_match_returns_none():
    assert normalize_title("Marketing Coordinator") is None


def test_empty_and_none_title():
    assert normalize_title("") is None
    assert normalize_title(None) is None


def test_is_support_role():
    assert is_support_role("paralegal") is True
    assert is_support_role("legal_assistant") is True
    assert is_support_role("intake_specialist") is True
    assert is_support_role("case_manager") is True
    assert is_support_role("document_collector") is True
    assert is_support_role("legal_receptionist") is True
    assert is_support_role("demand_writer") is True
    assert is_support_role("lien_negotiator") is True
    assert is_support_role("bookkeeper") is True
    assert is_support_role("attorney") is False
    assert is_support_role(None) is False
    assert is_support_role("not_a_real_slug") is False
