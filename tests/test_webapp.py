import asyncio

import httpx

import webapp


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
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"


def test_untrusted_host_is_rejected():
    response = request("GET", "/", headers={"host": "example.test"})

    assert response.status_code == 400


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
