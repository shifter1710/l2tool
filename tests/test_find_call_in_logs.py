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
