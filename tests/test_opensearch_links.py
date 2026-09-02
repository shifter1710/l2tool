from core import config, parser
from modules import (
    attached_call_myconnect,
    bff_logs_opensearch,
    profile_not_found_myconnect,
    sip_stack_opensearch,
)


def test_opensearch_links_stay_single_and_wide_with_multiple_event_times():
    ctx = parser.parse("""Номер клиента (msisdn): 79991234567
Дата и время проблемного звонка: 04.05.2026 10-49 11-01
""")
    ctx["tz"] = "Europe/Moscow"
    ctx["window"] = 60

    assert [str(value) for value in ctx["event_datetimes"]] == [
        "2026-05-04 10:49:00",
        "2026-05-04 11:01:00",
    ]

    bff_urls = bff_logs_opensearch.build(ctx)
    profile_urls = profile_not_found_myconnect.build(ctx)
    attached_urls = attached_call_myconnect.build(ctx)

    assert len(bff_urls) == 1
    expected_period = (
        "time:(from:'2026-05-04T10%3A47%3A00.000',"
        "to:'2026-05-04T12%3A31%3A00.000')"
    )
    assert expected_period in bff_urls[0]

    assert len(profile_urls) == 1
    assert expected_period in profile_urls[0]

    assert len(attached_urls) == 1
    assert expected_period in attached_urls[0]


def test_myconnect_call_builds_link_per_participant():
    ctx = parser.parse(
        """Номер клиента (msisdn): 79990000000
Номер принимающего звонок (Б): 79173442804, 79087803930
"""
    )

    urls = attached_call_myconnect.build(ctx)

    assert len(urls) == 2
    assert "sip%3A%2B79173442804" in urls[0]
    assert "sip%3A%2B79087803930" in urls[1]


def test_myconnect_call_reuses_myconnect_copied_url(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """[services.myconnect]
url = "https://shared-opensearch.test/discover?security_tenant=private#?_a=(metadata:(indexPattern:shared-myconnect-view))"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)

    url = attached_call_myconnect.build({"msisdn": "79990000000"})[0]

    assert url.startswith(
        "https://shared-opensearch.test/discover?security_tenant=private#"
    )
    assert "indexPattern:shared-myconnect-view" in url


def test_each_opensearch_service_uses_its_own_configured_period(
    monkeypatch,
    tmp_path,
):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """[opensearch]
base_url = "https://opensearch.test/discover"

[opensearch.index_patterns]
sip_stack = "sip-stack-view"
bff = "bff-view"
myconnect = "myconnect-view"

[services.sip_stack]
minutes_before = 11
minutes_after = 1

[services.bff]
minutes_before = 22
minutes_after = 2

[services.myconnect]
minutes_before = 33
minutes_after = 3

[services.myconnect_call]
minutes_before = 44
minutes_after = 4
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    ctx = parser.parse("""Номер клиента (msisdn): 79991234567
Дата и время проблемного звонка: 01.09.2026 12:00
""")
    ctx["tz"] = "Europe/Moscow"

    urls = {
        "sip_stack": sip_stack_opensearch.build(ctx)[0],
        "bff": bff_logs_opensearch.build(ctx)[0],
        "myconnect": profile_not_found_myconnect.build(ctx)[0],
        "myconnect_call": attached_call_myconnect.build(ctx)[0],
    }

    assert (
        "time:(from:'2026-09-01T11%3A49%3A00.000',"
        "to:'2026-09-01T12%3A01%3A00.000')"
    ) in urls["sip_stack"]
    assert (
        "time:(from:'2026-09-01T11%3A38%3A00.000',"
        "to:'2026-09-01T12%3A02%3A00.000')"
    ) in urls["bff"]
    assert (
        "time:(from:'2026-09-01T11%3A27%3A00.000',"
        "to:'2026-09-01T12%3A03%3A00.000')"
    ) in urls["myconnect"]
    assert (
        "time:(from:'2026-09-01T11%3A16%3A00.000',"
        "to:'2026-09-01T12%3A04%3A00.000')"
    ) in urls["myconnect_call"]
