from urllib.parse import parse_qs, urlparse

from core import parser
from modules import find_call_in_logs


def test_problem_call_datetime_builds_absolute_link_window():
    ctx = parser.parse("""Номер клиента (msisdn): 79990000000
Дата и время проблемного звонка: 04.05.2026, 12:28
""")
    ctx["tz"] = "Europe/Moscow"
    ctx["window"] = 60

    url = find_call_in_logs.build(ctx)[0]
    params = parse_qs(urlparse(url).query)

    assert params["from"] == ["2026-05-04T08:28:00.000Z"]
    assert params["to"] == ["2026-05-04T10:28:00.000Z"]
    assert "now-1h" not in url


def test_problem_call_date_only_builds_full_day_window():
    ctx = parser.parse("""Номер клиента (msisdn): 79990000000
Дата проблемного звонка: 04.05.2026
""")
    ctx["tz"] = "Europe/Moscow"

    url = find_call_in_logs.build(ctx)[0]
    params = parse_qs(urlparse(url).query)

    assert params["from"] == ["2026-05-03T21:00:00.000Z"]
    assert params["to"] == ["2026-05-04T21:00:00.000Z"]


def test_multiple_problem_call_datetimes_build_multiple_absolute_links():
    ctx = parser.parse("Дата и время проблемного звонка: 04.05.2026  10-49    11-01")
    ctx["tz"] = "Europe/Moscow"
    ctx["window"] = 60

    urls = find_call_in_logs.build(ctx)

    assert len(urls) == 2
    first_params = parse_qs(urlparse(urls[0]).query)
    second_params = parse_qs(urlparse(urls[1]).query)
    assert first_params["from"] == ["2026-05-04T06:49:00.000Z"]
    assert first_params["to"] == ["2026-05-04T08:49:00.000Z"]
    assert second_params["from"] == ["2026-05-04T07:01:00.000Z"]
    assert second_params["to"] == ["2026-05-04T09:01:00.000Z"]
    assert all("now-1h" not in url for url in urls)


def test_does_not_duplicate_same_phone_in_grafana_params():
    ctx = parser.parse("""Номер клиента (msisdn): 79144880859
Номер звонящего (А): любой
Номер принимающего звонок (Б): 914 488 0859
""")

    url = find_call_in_logs.build(ctx)[0]
    params = parse_qs(urlparse(url).query, keep_blank_values=True)

    assert ctx["phone_a_raw"] == "любой"
    assert ctx["phone_a"] is None
    assert params["var-phone"] == ["9144880859"]
    assert params["var-second_phone"] == [""]


def test_grafana_phone_a_uses_number_without_country_code():
    ctx = {"phone_a": "79999999999"}

    url = find_call_in_logs.build(ctx)[0]
    params = parse_qs(urlparse(url).query)

    assert params["var-phone"] == ["9999999999"]


def test_uses_context_timezone_in_grafana_url():
    ctx = parser.parse("Номер клиента (msisdn): 79990000000")
    ctx["tz"] = "Asia/Omsk"

    url = find_call_in_logs.build(ctx)[0]

    assert "timezone=Asia%2FOmsk" in url
