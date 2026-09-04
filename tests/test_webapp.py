import asyncio
import json
import re
from urllib.parse import urlencode

import httpx

import webapp
from core import dynamic_sources


def opensearch_example(index_pattern="web-bff"):
    return (
        "https://dashboards.example.local/app/data-explorer/discover"
        f"#?_a=(metadata:(indexPattern:{index_pattern},view:discover),"
        "query:(language:kuery,query:'msisdn:79991234567'))"
        "&_g=(time:(from:'2026-09-03T11:00:00.000',to:'2026-09-03T12:00:00.000'))"
    )


def grafana_uuid_example(call_uuid="12345678-1234-5678-1234-567812345678"):
    panes = {
        "A": {
            "queries": [{"refId": "A", "expr": f'{{job="calls"}} |= `{call_uuid}`'}],
            "range": {"from": "now-1h", "to": "now"},
        }
    }
    return "https://grafana.example.local/explore?" + urlencode(
        {"panes": json.dumps(panes, separators=(",", ":"))}
    )


def grafana_phone_pair_example():
    return (
        "https://grafana.example.local/d/calls/find-call-in-logs?orgId=1"
        "&var-phone=9835623921&var-second_phone=9994579778"
        "&from=2026-09-03T11:00:00.000Z&to=2026-09-03T12:00:00.000Z"
    )


def request(method, path, **kwargs):
    async def send():
        transport = httpx.ASGITransport(app=webapp.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://localhost",
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def valid_ticket():
    return "\n".join(
        [
            "Номер клиента (msisdn): 79991234567",
            "Номер звонящего (А): 79991234567",
            "Номер принимающего звонок (Б): 79997654321",
            "Дата и время проблемного звонка: 03.09.2026 14:30",
            "Местонахождение абонента: Москва",
        ]
    )


def test_home_is_local_and_has_security_headers():
    response = request("GET", "/")

    assert response.status_code == 200
    assert "Только на этом компьютере" in response.text
    assert 'action="/analyze#result"' in response.text
    assert "data-theme-toggle" in response.text
    assert '/static/app.js' in response.text
    assert 'type="datetime-local"' in response.text
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"


def test_untrusted_host_is_rejected():
    response = request("GET", "/", headers={"host": "example.test"})

    assert response.status_code == 400


def test_settings_page_lists_editable_sources():
    save_response = request(
        "POST",
        "/settings/source",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "name": "Свёрнутый блок",
            "product": "recording",
            "level": "number",
            "example_url": opensearch_example(),
            "sample_value": "",
            "minutes_before": "2",
            "minutes_after": "90",
        },
    )
    assert save_response.status_code == 303

    response = request("GET", "/settings")

    assert response.status_code == 200
    assert "Свои диагностические блоки" in response.text
    assert "Распознать и добавить" in response.text
    assert "OpenSearch" in response.text
    assert "Grafana" in response.text
    assert response.text.count("Поиск по номерам") >= 5
    assert response.text.count("Поиск по UUID") >= 5
    assert "product-recording" in response.text
    assert "product-secretary" in response.text
    assert "styles.css?v=20260904-8" in response.text
    assert 'class="config-level config-level-number"' in response.text
    assert 'class="config-level level-number"' not in response.text
    assert 'action="/settings/import"' in response.text
    assert "Скачать текущий" in response.text
    assert '<details class="panel source-card is-configured">' in response.text
    assert 'formaction="/settings/source/delete"' in response.text
    assert "data-confirm-delete=" in response.text
    assert "Свёрнутый блок" in response.text


def test_settings_levels_use_non_shrinking_vertical_layout():
    response = request("GET", "/static/styles.css")

    assert response.status_code == 200
    assert ".product-levels { display: flex" in response.text
    assert "flex: 0 0 auto" in response.text


def test_settings_can_add_rename_and_delete_a_source():
    save_response = request(
        "POST",
        "/settings/source",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "name": "Мой BFF",
            "product": "recording",
            "level": "number",
            "example_url": opensearch_example(),
            "sample_value": "",
            "minutes_before": "2",
            "minutes_after": "90",
        },
    )

    assert save_response.status_code == 303
    source = dynamic_sources.list_sources()[0]
    assert source["name"] == "Мой BFF"

    rename_response = request(
        "POST",
        "/settings/source",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "source_id": source["id"],
            "name": "BFF после переименования",
            "product": "calls",
            "level": "number",
            "example_url": opensearch_example(),
            "sample_value": "",
            "minutes_before": "2",
            "minutes_after": "90",
        },
    )
    assert rename_response.status_code == 303
    assert dynamic_sources.list_sources()[0]["name"] == "BFF после переименования"

    delete_response = request(
        "POST",
        "/settings/source/delete",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "source_id": source["id"],
        },
    )

    assert delete_response.status_code == 303
    assert dynamic_sources.list_sources() == []


def test_settings_imports_and_exports_dynamic_config():
    payload = json.dumps(
        {
            "version": 1,
            "sources": [
                {
                    "name": "Импортированный BFF",
                    "product": "recording",
                    "level": "number",
                    "example_url": opensearch_example("imported-view"),
                    "sample_value": "",
                    "minutes_before": 2,
                    "minutes_after": 90,
                }
            ],
        }
    ).encode()
    response = request(
        "POST",
        "/settings/import",
        data={"csrf_token": webapp.app.state.csrf_token},
        files={"config_file": ("diagnostic_sources.json", payload, "application/json")},
    )

    assert response.status_code == 303
    assert "imported=1" in response.headers["location"]
    assert dynamic_sources.list_sources()[0]["name"] == "Импортированный BFF"

    export_response = request("GET", "/settings/export")
    assert export_response.status_code == 200
    assert export_response.json()["sources"][0]["name"] == "Импортированный BFF"
    assert "diagnostic_sources.json" in export_response.headers["content-disposition"]


def test_settings_rejects_invalid_config_without_partial_import():
    response = request(
        "POST",
        "/settings/import",
        data={"csrf_token": webapp.app.state.csrf_token},
        files={"config_file": ("diagnostic_sources.json", b'{"sources":[{}]}', "application/json")},
    )

    assert response.status_code == 400
    assert "Блок 1" in response.text
    assert dynamic_sources.list_sources() == []


def test_saved_source_is_used_by_next_diagnostic_run():
    save_response = request(
        "POST",
        "/settings/source",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "name": "Произвольное имя блока",
            "product": "recording",
            "level": "number",
            "example_url": opensearch_example("new-bff-view"),
            "sample_value": "",
            "minutes_before": "2",
            "minutes_after": "90",
        },
    )
    analyze_response = request(
        "POST",
        "/analyze",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product": "recording",
            "window": "60",
            "ticket_text": valid_ticket(),
        },
    )

    assert save_response.status_code == 303
    assert analyze_response.status_code == 200
    assert "new-bff-view" in analyze_response.text
    assert "Произвольное имя блока" in analyze_response.text


def test_two_slot_link_uses_client_when_a_and_b_are_missing():
    dynamic_sources.save_source(
        {
            "name": "Парный поиск",
            "product": "recording",
            "level": "number",
            "example_url": grafana_phone_pair_example(),
            "sample_value": "",
            "minutes_before": 60,
            "minutes_after": 60,
        }
    )
    ticket = "\n".join(
        [
            "Номер клиента (msisdn): 79991234567",
            "Дата и время проблемного звонка: 03.09.2026 14:30",
            "Местонахождение абонента: Москва",
        ]
    )
    response = request(
        "POST",
        "/analyze",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product": "recording",
            "window": "60",
            "ticket_text": ticket,
        },
    )

    assert response.status_code == 200
    assert response.text.count('class="open-link"') == 1
    assert "var-phone=9991234567" in response.text
    assert "var-second_phone=9991234567" in response.text


def test_two_slot_link_completes_missing_b_with_client_number():
    dynamic_sources.save_source(
        {
            "name": "Парный поиск",
            "product": "recording",
            "level": "number",
            "example_url": grafana_phone_pair_example(),
            "sample_value": "",
            "minutes_before": 60,
            "minutes_after": 60,
        }
    )
    ticket = "\n".join(
        [
            "Номер клиента (msisdn): 79157771575",
            "Номер звонящего (А): 79209264847",
            "Дата и время проблемного звонка: 03.09.2026 14:30",
            "Местонахождение абонента: Москва",
        ]
    )
    response = request(
        "POST",
        "/analyze",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product": "recording",
            "window": "60",
            "ticket_text": ticket,
        },
    )

    assert response.status_code == 200
    assert response.text.count('class="open-link"') == 1
    assert "var-phone=9209264847" in response.text
    assert "var-second_phone=9157771575" in response.text


def test_post_requires_current_csrf_token():
    response = request(
        "POST",
        "/analyze",
        data={"csrf_token": "wrong", "ticket_text": valid_ticket()},
    )

    assert response.status_code == 403


def test_analyze_renders_parsed_values_and_links():
    response = request(
        "POST",
        "/analyze",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product": "recording",
            "window": "60",
            "ticket_text": valid_ticket(),
        },
    )

    assert response.status_code == 200
    assert "Первичная диагностика" in response.text
    assert "79991234567" in response.text
    assert "Диагностические ссылки" in response.text
    assert "grafana.example.local" in response.text
    assert "dashboards.example.local" in response.text
    assert "data-copy-link" in response.text
    assert "Копировать" in response.text
    assert "Скопировать все ссылки" in response.text
    assert 'class="url-details"' in response.text
    assert "service-icon--grafana" in response.text
    assert "service-icon--opensearch" in response.text
    assert re.search(
        r"Номер А.*?79991234567.*?client-badge.*?Клиент",
        response.text,
        re.DOTALL,
    )
    assert "<dt>Часовой пояс</dt>" not in response.text
    assert re.search(
        r"<dt>Регион</dt>.*?Москва.*?timezone-badge.*?\+3",
        response.text,
        re.DOTALL,
    )
    assert "+3 часа" not in response.text


def test_utc_offset_supports_non_integer_timezones():
    assert webapp.utc_offset_label(
        {
            "tz": "Asia/Kolkata",
            "event_time": webapp.datetime(2026, 9, 3, 14, 30),
        }
    ) == "+5:30"


def test_client_number_falls_back_to_separate_row_when_it_matches_neither_side():
    ticket = valid_ticket().replace(
        "Номер клиента (msisdn): 79991234567",
        "Номер клиента (msisdn): 79990000001",
    )
    response = request(
        "POST",
        "/analyze",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product": "recording",
            "window": "60",
            "ticket_text": ticket,
        },
    )

    assert response.status_code == 200
    assert "client-unmatched" in response.text
    assert "79990000001" in response.text


def test_history_matches_render_dates_and_paths(monkeypatch):
    monkeypatch.setattr(
        webapp.history,
        "find_matches",
        lambda ctx, **_kwargs: {
            "79991234567": [
                "history/2026/09/2026-09-03_79991234567_ab12cd34.yaml",
                "history/2026/08/2026-08-14_79991234567_ff00ff00.yaml",
            ]
        },
    )
    response = request(
        "POST",
        "/analyze",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product": "recording",
            "window": "60",
            "ticket_text": valid_ticket(),
        },
    )

    assert response.status_code == 200
    assert "Найдены похожие заявки в локальной истории" in response.text
    assert "<time datetime=\"2026-09-03\">2026-09-03</time>" in response.text
    assert "<time datetime=\"2026-08-14\">2026-08-14</time>" in response.text
    assert "history/2026/09/2026-09-03_79991234567_ab12cd34.yaml" in response.text
    assert "history/2026/08/2026-08-14_79991234567_ff00ff00.yaml" in response.text


def test_analyze_returns_partial_fragment_for_xhr():
    response = request(
        "POST",
        "/analyze",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product": "recording",
            "window": "60",
            "ticket_text": valid_ticket(),
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    assert "<!doctype html>" not in response.text.lower()
    assert "<html" not in response.text
    assert "<body" not in response.text
    assert 'id="result"' in response.text
    assert "Первичная диагностика" in response.text
    assert 'id="result-zone"' not in response.text


def test_analyze_xhr_error_returns_fragment_with_alert():
    response = request(
        "POST",
        "/analyze",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product": "recording",
            "window": "60",
            "ticket_text": "",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 400
    assert "<!doctype html>" not in response.text.lower()
    assert "alert-error" in response.text
    assert "Вставьте текст заявки" in response.text


def test_xhr_without_csrf_token_is_rejected():
    response = request(
        "POST",
        "/analyze",
        data={"ticket_text": valid_ticket()},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 403


def test_theme_and_copy_script_is_served_locally():
    response = request("GET", "/static/app.js")

    assert response.status_code == 200
    assert "localStorage" in response.text
    assert "navigator.clipboard" in response.text
    assert response.headers["cache-control"] == "no-store"


def test_correction_overrides_a_parsed_field():
    response = request(
        "POST",
        "/analyze",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product": "recording",
            "window": "60",
            "ticket_text": valid_ticket(),
            "override_msisdn": "79990001122",
        },
    )

    assert response.status_code == 200
    assert "79990001122" in response.text


def test_calendar_datetime_overrides_ticket_datetime():
    response = request(
        "POST",
        "/analyze",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product": "recording",
            "window": "60",
            "ticket_text": valid_ticket(),
            "override_event_datetime_picker": "2026-09-04T09:15",
        },
    )

    assert response.status_code == 200
    assert "04.09.2026 09:15:00" in response.text
    assert 'value="2026-09-04T09:15"' in response.text


def test_calendar_rejects_invalid_datetime():
    response = request(
        "POST",
        "/analyze",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product": "recording",
            "window": "60",
            "ticket_text": valid_ticket(),
            "override_event_datetime_picker": "invalid",
        },
    )

    assert response.status_code == 400
    assert "корректные дату и время" in response.text


def test_secondary_rejects_invalid_uuid_without_losing_primary_result():
    response = request(
        "POST",
        "/secondary",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product": "recording",
            "window": "60",
            "effective_ticket_text": valid_ticket(),
            "call_uuid": "not-a-uuid",
            "secondary_mode": "mgw",
        },
    )

    assert response.status_code == 400
    assert "Первичная диагностика" in response.text
    assert "UUID" in response.text
    assert "not-a-uuid" in response.text


def test_secondary_builds_mgw_link_for_valid_uuid():
    call_uuid = "12345678-1234-5678-1234-567812345678"
    response = request(
        "POST",
        "/secondary",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product": "recording",
            "window": "60",
            "effective_ticket_text": valid_ticket(),
            "call_uuid": call_uuid,
            "secondary_mode": "mgw",
        },
    )

    assert response.status_code == 200
    assert "Вторичная диагностика по UUID" in response.text
    assert "Запись / MGW / Loki" in response.text
    assert call_uuid in response.text


def test_custom_uuid_block_is_used_for_any_configured_product():
    common = {"csrf_token": webapp.app.state.csrf_token, "product": "calls"}
    number_response = request(
        "POST",
        "/settings/source",
        data={
            **common,
            "name": "Поиск номера",
            "level": "number",
            "example_url": opensearch_example("calls-view"),
            "minutes_before": "2",
            "minutes_after": "90",
        },
    )
    uuid_response = request(
        "POST",
        "/settings/source",
        data={
            **common,
            "name": "Мой UUID блок",
            "level": "uuid",
            "example_url": grafana_uuid_example(),
            "minutes_before": "2",
            "minutes_after": "90",
        },
    )
    call_uuid = "87654321-4321-8765-4321-876543218765"
    response = request(
        "POST",
        "/secondary",
        data={
            **common,
            "window": "60",
            "effective_ticket_text": valid_ticket(),
            "call_uuid": call_uuid,
        },
    )

    assert number_response.status_code == 303
    assert uuid_response.status_code == 303
    assert response.status_code == 200
    assert "Мой UUID блок" in response.text
    assert call_uuid in response.text


def test_secondary_is_restricted_to_recording_product():
    response = request(
        "POST",
        "/secondary",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product": "calls",
            "window": "60",
            "effective_ticket_text": valid_ticket(),
            "call_uuid": "12345678-1234-5678-1234-567812345678",
            "secondary_mode": "mgw",
        },
    )

    assert response.status_code == 400
    assert "только для продукта" in response.text


def test_batch_returns_generated_workbook(monkeypatch):
    def fake_process_table(_input_path, output_path):
        output_path.write_bytes(b"generated-workbook")

    monkeypatch.setattr(webapp, "process_table", fake_process_table)
    response = request(
        "POST",
        "/batch",
        data={"csrf_token": webapp.app.state.csrf_token},
        files={"table_file": ("calls.csv", b"header\nvalue\n", "text/csv")},
    )

    assert response.status_code == 200
    assert response.content == b"generated-workbook"
    assert response.headers["content-disposition"].endswith('filename="calls.cleaned.xlsx"')


def test_batch_rejects_unsupported_extension():
    response = request(
        "POST",
        "/batch",
        data={"csrf_token": webapp.app.state.csrf_token},
        files={"table_file": ("calls.exe", b"not-a-table", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert "XLSX" in response.text


def test_settings_pages_survive_corrupted_store(monkeypatch, tmp_path):
    store_path = tmp_path / "diagnostic_sources.json"
    store_path.write_text("{broken json", encoding="utf-8")
    monkeypatch.setattr(dynamic_sources, "STORE_PATH", store_path)

    settings_response = request("GET", "/settings")
    export_response = request("GET", "/settings/export")

    assert settings_response.status_code == 400
    assert "diagnostic_sources.json" in settings_response.text
    assert export_response.status_code == 400
    assert "diagnostic_sources.json" in export_response.text


def test_settings_products_section_and_crud():
    response = request("GET", "/settings")

    assert response.status_code == 200
    assert "Продукты" in response.text
    assert "Добавить продукт" in response.text

    create_response = request(
        "POST",
        "/settings/product",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "key": "zapis-msk",
            "title": "Запись МСК",
            "color": "violet",
        },
    )
    rename_response = request(
        "POST",
        "/settings/product",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product_key": "zapis-msk",
            "key": "zapis-spb",
            "title": "Запись СПБ",
            "color": "teal",
        },
    )
    delete_response = request(
        "POST",
        "/settings/product/delete",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product_key": "zapis-spb",
        },
    )

    assert create_response.status_code == 303
    assert rename_response.status_code == 303
    assert delete_response.status_code == 303
    assert dynamic_sources.list_sources() == []

    forbidden = request(
        "POST",
        "/settings/product/delete",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product_key": "recording",
        },
    )
    assert forbidden.status_code == 303


def test_settings_rejects_invalid_product_key():
    response = request(
        "POST",
        "/settings/product",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "key": "Плохой Ключ",
            "title": "Продукт",
            "color": "",
        },
    )

    assert response.status_code == 400
    assert "латиница" in response.text


def test_settings_toggle_move_and_duplicate_source():
    first = dynamic_sources.save_source(
        {
            "name": "Первый",
            "product": "recording",
            "level": "number",
            "example_url": opensearch_example("first-view"),
            "sample_value": "",
            "minutes_before": 2,
            "minutes_after": 90,
        }
    )
    second = dynamic_sources.save_source(
        {
            "name": "Второй",
            "product": "recording",
            "level": "number",
            "example_url": opensearch_example("second-view"),
            "sample_value": "",
            "minutes_before": 2,
            "minutes_after": 90,
        }
    )

    duplicate_response = request(
        "POST",
        "/settings/source/duplicate",
        data={"csrf_token": webapp.app.state.csrf_token, "source_id": second["id"]},
    )
    move_response = request(
        "POST",
        "/settings/source/move",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "source_id": second["id"],
            "direction": "up",
        },
    )
    toggle_response = request(
        "POST",
        "/settings/source/toggle",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "source_id": first["id"],
            "enabled": "0",
        },
    )
    bulk_response = request(
        "POST",
        "/settings/product/toggle-all",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product_key": "recording",
            "enabled": "1",
        },
    )

    assert duplicate_response.status_code == 303
    assert move_response.status_code == 303
    assert toggle_response.status_code == 303
    assert bulk_response.status_code == 303
    names = [item["name"] for item in dynamic_sources.list_sources()]
    assert names == ["Второй", "Первый", "Второй (копия)"]
    assert all(item["enabled"] for item in dynamic_sources.list_sources())

    settings_page = request("GET", "/settings")
    assert settings_page.text.count('class="source-status"') >= 3


def test_settings_preview_builds_link_without_saving():
    before = dynamic_sources.list_sources()

    response = request(
        "POST",
        "/settings/source/preview",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "name": "Черновик BFF",
            "product": "recording",
            "level": "number",
            "example_url": opensearch_example("preview-view"),
            "sample_value": "",
            "minutes_before": "2",
            "minutes_after": "90",
            "preview_value": "79991230001",
        },
    )

    assert response.status_code == 200
    assert "Проверка ссылки" in response.text
    assert "msisdn:79991230001" in response.text
    assert "Открыть в новой вкладке" in response.text
    assert dynamic_sources.list_sources() == before

    broken = request(
        "POST",
        "/settings/source/preview",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "name": "Сломанный",
            "product": "recording",
            "level": "number",
            "example_url": "https://example.local/without-number",
            "sample_value": "",
            "preview_value": "79991230001",
        },
    )

    assert broken.status_code == 400
    assert "Ссылка не собирается" in broken.text
    assert dynamic_sources.list_sources() == before


def test_settings_backups_list_and_restore_roundtrip():
    created = dynamic_sources.save_source(
        {
            "name": "Для отката",
            "product": "recording",
            "level": "number",
            "example_url": opensearch_example("backup-view"),
            "sample_value": "",
            "minutes_before": 2,
            "minutes_after": 90,
        }
    )
    delete_response = request(
        "POST",
        "/settings/source/delete",
        data={"csrf_token": webapp.app.state.csrf_token, "source_id": created["id"]},
    )
    assert delete_response.status_code == 303
    assert dynamic_sources.list_sources() == []

    page = request("GET", "/settings")
    assert "Резервные копии" in page.text
    backup_name = page.text.split('name="backup_name" value="', 1)[1].split('"', 1)[0]

    restore_response = request(
        "POST",
        "/settings/backup/restore",
        data={"csrf_token": webapp.app.state.csrf_token, "backup_name": backup_name},
    )

    assert restore_response.status_code == 303
    assert [item["name"] for item in dynamic_sources.list_sources()] == ["Для отката"]

    traversal = request(
        "POST",
        "/settings/backup/restore",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "backup_name": "../../diagnostic_sources.json",
        },
    )
    assert traversal.status_code == 400


def test_settings_import_toml_renders_report(monkeypatch, tmp_path):
    from core import config as config_module

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[services.zapis]",
                'url = "https://grafana.example.local/d/example/find-call-in-logs'
                '?orgId=000&var-phone=9835623921&var-second_phone=9994579778'
                '&from=2026-09-03T11:00:00.000Z&to=2026-09-03T12:00:00.000Z"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)

    response = request(
        "POST",
        "/settings/import-toml",
        data={"csrf_token": webapp.app.state.csrf_token, "product": "recording"},
    )

    assert response.status_code == 200
    assert "Отчёт о переносе" in response.text
    assert "Добавлено блоков: 1" in response.text
    assert [item["name"] for item in dynamic_sources.list_sources()] == [
        "Grafana / find-call-in-logs"
    ]
    assert dynamic_sources.list_sources()[0]["strategy"] == "national"


def write_runbook_case(case):
    from core import runbook

    return runbook.save_case(case)


def runbook_case(source_id=None, symptom="Запись есть, транскрипта нет"):
    return {
        "id": "no-transcript",
        "symptom": symptom,
        "steps": [
            {"source": source_id, "note": "Проверить приход звонка в конвейер"},
            {"source": None, "note": "Уточнить у абонента детали"},
        ],
    }


def test_home_shows_collapsed_runbook_panel_with_case_buttons():
    write_runbook_case(runbook_case())

    response = request("GET", "/")

    assert response.status_code == 200
    assert "Куда смотреть?" in response.text
    assert 'action="/runbook"' in response.text
    assert "Запись есть, транскрипта нет" in response.text
    assert 'name="case_id" value="no-transcript"' in response.text


def test_home_hides_runbook_panel_when_store_is_empty():
    response = request("GET", "/")

    assert response.status_code == 200
    assert "Куда смотреть?" not in response.text


def test_runbook_renders_steps_with_links_from_last_ticket():
    source = dynamic_sources.save_source(
        {
            "name": "BFF конвейер",
            "product": "recording",
            "level": "number",
            "example_url": opensearch_example("runbook-view"),
            "sample_value": "",
            "minutes_before": 2,
            "minutes_after": 90,
        }
    )
    write_runbook_case(runbook_case(source_id=source["id"]))

    response = request(
        "POST",
        "/runbook",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "case_id": "no-transcript",
            "product": "recording",
            "window": "60",
            "effective_ticket_text": valid_ticket(),
        },
    )

    assert response.status_code == 200
    assert "Порядок проверки" in response.text
    assert "BFF конвейер" in response.text
    assert "runbook-view" in response.text
    assert "msisdn:79991234567" in response.text
    assert "Уточнить у абонента" in response.text
    assert 'class="open-link"' in response.text


def test_runbook_without_ticket_shows_hint_instead_of_links():
    source = dynamic_sources.save_source(
        {
            "name": "BFF конвейер",
            "product": "recording",
            "level": "number",
            "example_url": opensearch_example("runbook-view"),
            "sample_value": "",
            "minutes_before": 2,
            "minutes_after": 90,
        }
    )
    write_runbook_case(runbook_case(source_id=source["id"]))

    response = request(
        "POST",
        "/runbook",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "case_id": "no-transcript",
            "product": "recording",
            "window": "60",
        },
    )

    assert response.status_code == 200
    assert "Сначала разберите заявку" in response.text
    assert 'class="open-link"' not in response.text


def test_runbook_step_with_missing_source_is_text_without_link():
    write_runbook_case(runbook_case(source_id="missing-block"))

    response = request(
        "POST",
        "/runbook",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "case_id": "no-transcript",
            "product": "recording",
            "window": "60",
            "effective_ticket_text": valid_ticket(),
        },
    )

    assert response.status_code == 200
    assert "не найден в настройках" in response.text
    assert 'class="open-link"' not in response.text
    assert "Проверить приход звонка" in response.text


def test_runbook_unknown_case_returns_404():
    response = request(
        "POST",
        "/runbook",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "case_id": "ghost",
            "product": "recording",
            "window": "60",
        },
    )

    assert response.status_code == 404
    assert "Кейс ранбука не найден" in response.text


def test_runbook_requires_csrf_token():
    write_runbook_case(runbook_case())

    response = request(
        "POST",
        "/runbook",
        data={"case_id": "no-transcript", "product": "recording", "window": "60"},
    )

    assert response.status_code == 403


def test_settings_runbook_crud_from_site():
    source = dynamic_sources.save_source(
        {
            "name": "BFF конвейер",
            "product": "recording",
            "level": "number",
            "example_url": opensearch_example("runbook-view"),
            "sample_value": "",
            "minutes_before": 2,
            "minutes_after": 90,
        }
    )
    page = request("GET", "/settings")
    assert 'id="runbook"' in page.text
    assert "Ранбук «куда смотреть»" in page.text
    assert source["name"] in page.text
    assert "Без ссылки — просто текст" in page.text

    create_response = request(
        "POST",
        "/settings/runbook",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "symptom": "Нет транскрипта",
            "case_key": "no-transcript",
            "step_source_1": source["id"],
            "step_note_1": "Проверить конвейер",
            "step_note_2": "Уточнить у абонента",
        },
    )
    assert create_response.status_code == 303
    cases = list(webapp.runbook.load_store())
    assert len(cases) == 1
    assert cases[0]["steps"][1]["source"] is None

    update_response = request(
        "POST",
        "/settings/runbook",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "case_id": "no-transcript",
            "symptom": "Транскрипта нет — обновлено",
            "step_note_1": "Новый шаг",
        },
    )
    assert update_response.status_code == 303
    updated = webapp.runbook.load_store()[0]
    assert updated["symptom"] == "Транскрипта нет — обновлено"
    assert updated["steps"] == [{"source": None, "note": "Новый шаг"}]

    delete_response = request(
        "POST",
        "/settings/runbook/delete",
        data={"csrf_token": webapp.app.state.csrf_token, "case_id": "no-transcript"},
    )
    assert delete_response.status_code == 303
    assert webapp.runbook.load_store() == []


def test_settings_runbook_rejects_case_without_steps():
    response = request(
        "POST",
        "/settings/runbook",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "symptom": "Пустой кейс",
            "case_key": "empty-case",
        },
    )

    assert response.status_code == 400
    assert "шаг" in response.text
    assert webapp.runbook.load_store() == []


def test_settings_runbook_import_and_export_roundtrip():
    write_runbook_case(runbook_case())
    export_response = request("GET", "/settings/runbook/export")

    assert export_response.status_code == 200
    assert export_response.json()[0]["id"] == "no-transcript"
    assert "runbook.json" in export_response.headers["content-disposition"]

    payload = json.dumps(
        [dict(runbook_case(symptom="Другой симптом"), id="other-case")],
        ensure_ascii=False,
    ).encode()
    import_response = request(
        "POST",
        "/settings/runbook/import",
        data={"csrf_token": webapp.app.state.csrf_token},
        files={"runbook_file": ("runbook.json", payload, "application/json")},
    )

    assert import_response.status_code == 303
    assert "runbook_imported=1" in import_response.headers["location"]
    assert [case["id"] for case in webapp.runbook.load_store()] == ["other-case"]


def test_settings_runbook_import_rejects_invalid_file_without_replacing():
    write_runbook_case(runbook_case())
    response = request(
        "POST",
        "/settings/runbook/import",
        data={"csrf_token": webapp.app.state.csrf_token},
        files={"runbook_file": ("runbook.json", b"[{}]", "application/json")},
    )

    assert response.status_code == 400
    assert "Кейс 1" in response.text
    assert [case["id"] for case in webapp.runbook.load_store()] == ["no-transcript"]


def test_settings_survives_broken_runbook_file():
    webapp.runbook.STORE_PATH.write_text("{broken", encoding="utf-8")
    webapp.runbook._LOAD_ERROR_LOGGED.clear()

    home = request("GET", "/")
    settings_page = request("GET", "/settings")
    case_response = request(
        "POST",
        "/runbook",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "case_id": "no-transcript",
            "product": "recording",
            "window": "60",
        },
    )

    assert home.status_code == 200
    assert settings_page.status_code == 200
    assert "empty-state" in settings_page.text
    assert case_response.status_code == 404
