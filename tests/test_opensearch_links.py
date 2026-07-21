from core import parser
from modules import attached_call_myconnect
from modules import bff_logs_opensearch
from modules import profile_not_found_myconnect


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
    assert "time:(from:now-1M,to:now)" in bff_urls[0]
    assert "2026-05-04T" not in bff_urls[0]

    assert len(profile_urls) == 1
    assert "time:(from:now-2M,to:now)" in profile_urls[0]
    assert "2026-05-04T" not in profile_urls[0]

    assert len(attached_urls) == 1
    assert "time:(from:now-2M,to:now)" in attached_urls[0]
    assert "2026-05-04T" not in attached_urls[0]


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
