from modules import sip_stack_opensearch


def test_sip_stack_query_uses_msisdn_without_leading_7():
    url = sip_stack_opensearch.build({"msisdn": "79999999999"})[0]

    assert "query:%2A9999999999" in url


def test_sip_stack_without_msisdn_returns_no_links():
    assert sip_stack_opensearch.build({}) == []
