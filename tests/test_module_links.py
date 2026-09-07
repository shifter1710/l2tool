"""Позитивные тесты построения ссылок модулями без собственного покрытия.

Конфигурацию сервисов даёт фикстура conftest (grafana.test-хосты заменены
на dashboards/grafana.example.local): bff и myconnect — Discover-ссылки,
zapis — дашборд Grafana для вторичной записи.
"""

from datetime import datetime
from urllib.parse import unquote, unquote_plus

import pytest

from core.utils import hash_phone
from modules import (
    attached_call_myconnect,
    bff_logs_opensearch,
    profile_not_found_myconnect,
    recording_collector,
    recording_crs,
    recording_vss_crs,
)


def ticket_ctx():
    return {
        "msisdn": "79991234567",
        "phone_a": "79991234567",
        "phone_b": "79997654321",
        "event_time": datetime(2026, 9, 1, 12, 0),
        "event_datetimes": [datetime(2026, 9, 1, 12, 0)],
        "tz": "Europe/Moscow",
        "window": 30,
    }


def recording_ctx():
    return {
        "call_uuid": "12345678-1234-5678-1234-567812345678",
        "event_time": datetime(2026, 9, 1, 12, 0),
        "event_datetimes": [datetime(2026, 9, 1, 12, 0)],
        "tz": "Europe/Moscow",
        "window": 30,
    }


@pytest.mark.parametrize(
    ("module", "selector"),
    [
        (recording_collector, "talk-recording-collector"),
        (recording_crs, "crs.service"),
        (recording_vss_crs, "vss.service"),
    ],
)
def test_recording_secondary_modules_build_loki_search(module, selector):
    url = module.build(recording_ctx())[0]
    decoded = unquote(url)

    assert url.startswith("https://grafana.example.local/")
    # селектор и UUID живут внутри JSON-параметра panes (кавычки экранированы)
    assert selector in decoded
    assert "12345678-1234-5678-1234-567812345678" in decoded


def test_bff_logs_search_uses_phone_hash_and_configured_view():
    url = bff_logs_opensearch.build(ticket_ctx())[0]
    decoded = unquote(url)

    assert url.startswith("https://dashboards.example.local/")
    assert "indexPattern:bff-example" in decoded
    assert f'"{hash_phone("79991234567")}"' in decoded
    assert "auth.msisdn" in decoded


def test_profile_not_found_search_pins_failure_phrase():
    url = profile_not_found_myconnect.build(ticket_ctx())[0]

    assert "indexPattern:myconnect-example" in unquote(url)
    assert "79991234567" in url
    # фильтр фразы отказа закодирован quote_plus внутри rison-состояния
    assert "failed starting call on IMS side: profile not found" in unquote_plus(url)


def test_attached_call_search_links_master_with_the_other_side():
    url = attached_call_myconnect.build(ticket_ctx())[0]
    decoded = unquote(url)

    assert '"master:79991234567" AND "sip:+79997654321"' in decoded


def test_attached_call_multi_party_builds_link_per_participant():
    ctx = ticket_ctx()
    ctx["phone_a_values"] = ["79991234567", "79151112233"]
    ctx["phone_b_values"] = ["79997654321"]

    urls = attached_call_myconnect.build(ctx)

    assert len(urls) == 2
    participants = ["79151112233", "79997654321"]
    for url, participant in zip(urls, participants, strict=True):
        decoded = unquote(url)
        assert '"master:79991234567"' in decoded
        assert f'"sip:+{participant}"' in decoded
