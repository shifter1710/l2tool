import json
from datetime import date, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest

from core import config
from modules import noise_loki, secretary_loki


def copied_explore_url(expression, time_from="now-5m"):
    pane = {
        "datasource": "loki-example",
        "queries": [{"refId": "A", "expr": expression}],
        "range": {"from": time_from, "to": "now"},
    }
    return "https://grafana.example.local/explore?" + urlencode(
        {
            "schemaVersion": "1",
            "panes": json.dumps({"A": pane}, separators=(",", ":")),
            "orgId": "000",
        }
    )


def configured_service(monkeypatch, tmp_path, service_name, url):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[services.{service_name}]\nurl = "{url}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)


def expression_and_range(url):
    params = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
    pane = json.loads(params["panes"])["A"]
    return pane["queries"][0]["expr"], pane["range"]


def test_secretary_replaces_phone_and_preserves_copied_time_range(
    monkeypatch,
    tmp_path,
):
    configured_service(
        monkeypatch,
        tmp_path,
        "secretary",
        copied_explore_url('{namespace="example"} |= `70000000000` |= ``'),
    )

    url = secretary_loki.build({"msisdn": "79991234567"})[0]
    expression, time_range = expression_and_range(url)

    assert expression == '{namespace="example"} |= `79991234567` |= ``'
    assert time_range == {"from": "now-5m", "to": "now"}


def test_secretary_uses_ticket_time_instead_of_copied_range(
    monkeypatch,
    tmp_path,
):
    configured_service(
        monkeypatch,
        tmp_path,
        "secretary",
        copied_explore_url('{namespace="example"} |= `70000000000`'),
    )
    ctx = {
        "msisdn": "79991234567",
        "event_time": datetime(2026, 9, 1, 12, 0),
        "event_datetimes": [datetime(2026, 9, 1, 12, 0)],
        "tz": "Europe/Moscow",
        "window": 60,
    }

    url = secretary_loki.build(ctx)[0]
    _expression, time_range = expression_and_range(url)

    assert time_range == {
        "from": "2026-09-01T08:00:00.000Z",
        "to": "2026-09-01T10:00:00.000Z",
    }


def test_secretary_builds_one_ticket_window_per_event_time(
    monkeypatch,
    tmp_path,
):
    configured_service(
        monkeypatch,
        tmp_path,
        "secretary",
        copied_explore_url('{namespace="example"} |= `70000000000`'),
    )
    ctx = {
        "msisdn": "79991234567",
        "event_datetimes": [
            datetime(2026, 9, 1, 12, 0),
            datetime(2026, 9, 1, 15, 0),
        ],
        "tz": "Europe/Moscow",
        "window": 30,
    }

    urls = secretary_loki.build(ctx)

    assert [expression_and_range(url)[1] for url in urls] == [
        {
            "from": "2026-09-01T08:30:00.000Z",
            "to": "2026-09-01T09:30:00.000Z",
        },
        {
            "from": "2026-09-01T11:30:00.000Z",
            "to": "2026-09-01T12:30:00.000Z",
        },
    ]


def test_noise_searches_by_ten_digit_phone(monkeypatch, tmp_path):
    configured_service(
        monkeypatch,
        tmp_path,
        "noise",
        copied_explore_url(
            '{job!=""} |= `9000000000`',
            time_from="now-24h",
        ),
    )

    url = noise_loki.build({"msisdn": "79991234567"})[0]
    expression, time_range = expression_and_range(url)

    assert expression == '{job!=""} |= `9991234567`'
    assert time_range == {"from": "now-24h", "to": "now"}


def test_noise_uses_full_ticket_day_when_only_date_is_known(monkeypatch, tmp_path):
    configured_service(
        monkeypatch,
        tmp_path,
        "noise",
        copied_explore_url('{job!=""} |= `9000000000`'),
    )

    url = noise_loki.build(
        {
            "msisdn": "79991234567",
            "event_date": date(2026, 9, 1),
            "tz": "Europe/Moscow",
            "window": 60,
        }
    )[0]
    _expression, time_range = expression_and_range(url)

    assert time_range == {
        "from": "2026-09-01T05:00:00.000Z",
        "to": "2026-09-01T17:00:00.000Z",
    }


def test_loki_product_links_need_a_phone():
    assert secretary_loki.build({}) == []
    assert noise_loki.build({}) == []


def test_copied_link_without_phone_filter_has_helpful_error(monkeypatch, tmp_path):
    configured_service(
        monkeypatch,
        tmp_path,
        "secretary",
        copied_explore_url('{namespace="example"}'),
    )

    with pytest.raises(ValueError, match="phone filter in backticks"):
        secretary_loki.build({"msisdn": "79991234567"})
