from modules import attached_call_myconnect, bff_logs_opensearch, profile_not_found_myconnect


def test_bff_without_phone_returns_no_links_and_prints_nothing(capsys):
    assert bff_logs_opensearch.build({}) == []
    assert capsys.readouterr().out == ""


def test_profile_not_found_without_msisdn_returns_no_links_and_prints_nothing(capsys):
    assert profile_not_found_myconnect.build({}) == []
    assert capsys.readouterr().out == ""


def test_attached_call_without_msisdn_returns_no_links_and_prints_nothing(capsys):
    assert attached_call_myconnect.build({}) == []
    assert capsys.readouterr().out == ""
