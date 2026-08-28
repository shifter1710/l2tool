from modules import sip_stack_opensearch


def test_sip_stack_query_uses_msisdn_without_leading_7():
    url = sip_stack_opensearch.build({"msisdn": "79180200695"})[0]

    assert "columns:!(message)" in url
    assert "metadata:(indexPattern:sip-stack-example,view:discover)" in url
    assert "query:%27%2A9180200695%27" in url
    assert "query:%2A9180200695" not in url


def test_sip_stack_query_keeps_short_msisdn_as_quoted_wildcard():
    url = sip_stack_opensearch.build({"msisdn": "9180200695"})[0]

    assert "query:%27%2A9180200695%27" in url
    assert "query:%2A9180200695" not in url


def test_sip_stack_without_msisdn_returns_no_links():
    assert sip_stack_opensearch.build({}) == []


def test_sip_stack_quotes_absolute_time_for_rison():
    url = sip_stack_opensearch.build_one(
        {"msisdn": "79180200695"},
        "2026-08-28T12:58:00.000",
        "2026-08-28T14:30:00.000",
    )

    assert (
        "time:(from:'2026-08-28T12:58:00.000',"
        "to:'2026-08-28T14:30:00.000')"
    ) in url
