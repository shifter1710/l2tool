from modules import sip_stack_opensearch


def test_sip_stack_query_uses_msisdn_without_leading_7():
    url = sip_stack_opensearch.build({"msisdn": "79180200695"})[0]

    assert "query:%27%2A9180200695%27" in url
    assert "query:%2A9180200695" not in url


def test_sip_stack_query_keeps_short_msisdn_as_quoted_wildcard():
    url = sip_stack_opensearch.build({"msisdn": "9180200695"})[0]

    assert "query:%27%2A9180200695%27" in url
    assert "query:%2A9180200695" not in url


def test_sip_stack_without_msisdn_returns_no_links():
    assert sip_stack_opensearch.build({}) == []
