import sys
from datetime import datetime
from pathlib import Path

import call_history as call_history_cli
import gtool
import webapp
from core import call_history, dynamic_sources
from core import config as config_module

# Сводный формат внешнего скрипта: диапазон времени с длительностью
# и строка участников. Слева — звонящий; «← В (условие)» — переадресация
# на номер клиента. Все номера синтетические.
HISTORY_SAMPLE = "\n".join(
    [
        "08.09.2026 10:00:18-10:03:09 (0:02:51)",
        "79991234567 → 79991000001",
        "",
        "08.09.2026 16:39:45-16:41:56 (0:02:11)",
        "79991000002 → 79991234567",
        "",
        "08.09.2026 18:27:02-18:33:02 (0:06:00)",
        "79991234567 → 79991000008",
        "",
        # Переадресация по «занято»: звонок на сервисный номер ушёл клиенту.
        "10.09.2026 19:03:51-19:04:09 (0:00:18)",
        "79991000009 → 79991230002 ← 79991234567 (занято)",
        "",
        # Переадресация от короткого кода.
        "10.09.2026 14:45:12-14:45:15 (0:00:03)",
        "0900 → 79991230001 ← 79991234567 (нет ответа)",
        "",
        "12.09.2026 12:35:41-12:44:48 (0:09:07)",
        "79991000012 → 79991234567",
    ]
)

# Прежний событийный формат — старые выгрузки остаются совместимы.
OLD_HISTORY_SAMPLE = "\n".join(
    [
        "2026-09-07 10:00:18 Связь. Исходящая (_Сотовые операторы)",
        "→ 79991000001 Duration: 171 SECOND",
        "      Цифровой звонок",
        "2026-09-07 16:39:45 Связь. Входящая (МТС Других регионов)",
        "    ← 79991000002 Duration: 131 SECOND",
        "      Цифровой звонок",
        # Тройная цепочка переадресации: сервисная нога до строки переадресации.
        "2026-09-08 14:45:12 Связь. Исходящая (Бесплатный сервисный номер)",
        "    → 79991230001 Duration: 4 SECOND",
        "      Интернет-звонки: VoLTE",
        "2026-09-08 14:45:12 Переадресация по условию “абонент недоступен” → 79991230001",
        "2026-09-08 14:45:12 Входящая связь: Сервисная линия (0900)",
        "    ← 0900 Duration: 3 SECOND",
        "      Интернет-звонки: VoLTE",
        # Звонок без строки типа.
        "2026-09-10 18:27:02 Связь. Исходящая (Нац и МН-роуминг, Россия)",
        "    → 79991000008 Duration: 360 SECOND",
        # Цепочка «занято»: сервисная нога стоит после входящей.
        "2026-09-10 19:03:51 Переадресация по условию “занято” → 79991230002",
        "2026-09-10 19:03:51 Связь. Входящая (При переадресации, Сотовые операторы)",
        "    ← 79991000009 Duration: 18 SECOND",
        "      Интернет-звонки: VoLTE",
        "2026-09-10 19:03:52 Связь. Исходящая (Бесплатный сервисный номер)",
        "    → 79991230002 Duration: 18 SECOND",
        "      Интернет-звонки: VoLTE",
        "2026-09-12 12:35:41 Безлимитный звонок на абонента МТС через Мой МТС",
        "    → 79991000012 Duration: 547 SECOND",
        "      Цифровой звонок",
        "",
        "Примечания:",
        "Цифровой звонок - это звонок через myconnect",
    ]
)


def find_call(calls, phone):
    return next(call for call in calls if call.remote_phone == phone)


def test_parse_range_format_directions_and_durations():
    calls = call_history.parse_call_history(HISTORY_SAMPLE, msisdn="79991234567")

    assert [call.remote_phone for call in calls] == [
        "79991000001",
        "79991000002",
        "79991000008",
        "0900",
        "79991000009",
        "79991000012",
    ]

    outgoing = find_call(calls, "79991000001")
    assert outgoing.direction == "out"
    assert outgoing.duration == 171
    assert outgoing.started_at == datetime(2026, 9, 8, 10, 0, 18)

    incoming = find_call(calls, "79991000002")
    assert incoming.direction == "in"
    assert incoming.duration == 131

    long_call = find_call(calls, "79991000012")
    assert long_call.direction == "in"
    assert long_call.duration == 547


def test_parse_range_format_forward_rows():
    calls = call_history.parse_call_history(HISTORY_SAMPLE, msisdn="79991234567")

    forwarded = find_call(calls, "79991000009")
    assert forwarded.direction == "in"
    assert forwarded.forward_condition == "занято"
    assert forwarded.service_phone == "79991230002"
    assert forwarded.duration == 18
    assert forwarded.legs == 3

    short_code = find_call(calls, "0900")
    assert short_code.direction == "in"
    assert short_code.forward_condition == "нет ответа"
    assert short_code.service_phone == "79991230001"


def test_parse_range_format_infers_subscriber_without_msisdn():
    with_msisdn = call_history.parse_call_history(HISTORY_SAMPLE, msisdn="79991234567")
    inferred = call_history.parse_call_history(HISTORY_SAMPLE)

    # 79991234567 участвует в каждой записи — направления выводятся те же.
    assert [(call.direction, call.remote_phone) for call in inferred] == [
        (call.direction, call.remote_phone) for call in with_msisdn
    ]


def test_parse_range_format_secretary_flag(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[call_history]\nsecretary_numbers = ["79991230002"]\n', encoding="utf-8"
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)

    history = "\n".join(
        [
            "10.09.2026 19:03:51-19:04:09 (0:00:18)",
            "79991000009 → 79991230002 ← 79991234567 (занято)",
            "10.09.2026 19:30:00-19:30:30 (0:00:30)",
            "79991234567 → 79991230002",
        ]
    )
    calls = call_history.parse_call_history(history, msisdn="79991234567")

    forwarded, plain = calls
    assert forwarded.secretary
    assert "Секретарь" in call_history.call_badges(forwarded)
    assert plain.secretary
    assert "Секретарь" in call_history.call_badges(plain)


def test_parse_event_format_still_supported():
    calls = call_history.parse_call_history(OLD_HISTORY_SAMPLE)

    assert len(calls) == 6
    assert [call.remote_phone for call in calls] == [
        "79991000001",
        "79991000002",
        "0900",
        "79991000008",
        "79991000009",
        "79991000012",
    ]


def test_event_format_forward_chain_with_service_leg_before():
    calls = call_history.parse_call_history(OLD_HISTORY_SAMPLE)
    forwarded = find_call(calls, "0900")

    assert forwarded.direction == "in"
    assert forwarded.forward_condition == "абонент недоступен"
    assert forwarded.service_phone == "79991230001"
    assert forwarded.remote_name == "Сервисная линия"
    assert forwarded.duration == 3
    assert forwarded.call_type == "Интернет-звонки: VoLTE"
    assert forwarded.legs == 3
    # Сервисная нога не остаётся отдельным звонком.
    assert not any(call.remote_phone == "79991230001" for call in calls)


def test_event_format_forward_chain_with_service_leg_after():
    calls = call_history.parse_call_history(OLD_HISTORY_SAMPLE)
    forwarded = find_call(calls, "79991000009")

    assert forwarded.forward_condition == "занято"
    assert forwarded.service_phone == "79991230002"
    assert forwarded.duration == 18
    assert forwarded.legs == 3
    assert not any(call.remote_phone == "79991230002" for call in calls)


def test_event_format_plain_calls_keep_direction_and_type():
    calls = call_history.parse_call_history(OLD_HISTORY_SAMPLE)

    outgoing = find_call(calls, "79991000001")
    assert outgoing.direction == "out"
    assert outgoing.digital
    assert outgoing.duration == 171

    incoming = find_call(calls, "79991000002")
    assert incoming.direction == "in"
    assert incoming.digital

    roaming = find_call(calls, "79991000008")
    assert roaming.call_type is None
    assert not roaming.digital

    app_call = find_call(calls, "79991000012")
    assert app_call.via_app
    assert app_call.digital


def test_normalize_remote_phone():
    assert call_history.normalize_remote_phone("79991000001") == "79991000001"
    assert call_history.normalize_remote_phone("89991000001") == "79991000001"
    assert call_history.normalize_remote_phone("9991000001") == "79991000001"
    assert call_history.normalize_remote_phone("+7 999 100-00-01") == "79991000001"
    assert call_history.normalize_remote_phone("0900") == "0900"


def test_secretary_flag_from_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[call_history]\nsecretary_numbers = ["79991230999", "89991230998"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)

    history = "\n".join(
        [
            "2026-09-08 14:45:12 Переадресация по условию “занято” → 79991230999",
            "2026-09-08 14:45:12 Связь. Входящая (При переадресации, Сотовые операторы)",
            "    ← 79991000009 Duration: 18 SECOND",
            "2026-09-08 15:00:00 Связь. Исходящая (_Сотовые операторы)",
            "    → 79991230998 Duration: 30 SECOND",
        ]
    )
    calls = call_history.parse_call_history(history)

    forwarded, plain = calls
    assert forwarded.secretary
    assert "Секретарь" in call_history.call_badges(forwarded)
    assert plain.secretary
    assert "Секретарь" in call_history.call_badges(plain)


def test_secretary_numbers_saved_on_site_take_precedence(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[call_history]\nsecretary_numbers = ["79991230999"]\n', encoding="utf-8"
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)

    # Пока на сайте номера не сохранялись — работает config.toml.
    assert call_history.secretary_numbers_ordered() == ["79991230999"]

    saved = dynamic_sources.save_call_history_secretary_numbers(
        "89991230555, 79991230444\n89991230555"
    )
    assert saved == ["79991230555", "79991230444"]
    assert dynamic_sources.load_call_history() == {
        "secretary_numbers": ["79991230555", "79991230444"]
    }
    assert call_history.secretary_numbers_ordered() == [
        "79991230555",
        "79991230444",
    ]

    # Пустой список на сайте тоже приоритетнее — метки выключаются.
    dynamic_sources.save_call_history_secretary_numbers("")
    assert call_history.secretary_numbers_ordered() == []


def test_save_secretary_numbers_validates_input():
    try:
        dynamic_sources.save_call_history_secretary_numbers("79991230999, 0900")
    except ValueError as error:
        assert "0900" in str(error)
    else:
        raise AssertionError("expected ValueError")

    try:
        dynamic_sources.save_call_history_secretary_numbers(
            "\n".join(f"79991230{i:03d}" for i in range(51))
        )
    except ValueError as error:
        assert "не больше 50" in str(error)
    else:
        raise AssertionError("expected ValueError")
    assert dynamic_sources.load_call_history().get("secretary_numbers") is None


def test_settings_call_history_route_saves_numbers():
    response = webapp_request(
        "POST",
        "/settings/call-history",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "secretary_numbers": "89991230999\n79991230086",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/settings?call_history_saved=1#call-history"
    assert call_history.secretary_numbers_ordered() == [
        "79991230999",
        "79991230086",
    ]

    page = webapp_request("GET", "/settings?call_history_saved=1")
    assert page.status_code == 200
    assert "Номера Секретаря сохранены" in page.text
    assert "79991230086" in page.text

    bad = webapp_request(
        "POST",
        "/settings/call-history",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "secretary_numbers": "не номер",
        },
    )
    assert bad.status_code == 400
    assert "Номер Секретаря указан некорректно" in bad.text
    assert call_history.secretary_numbers_ordered() == [
        "79991230999",
        "79991230086",
    ]


def test_call_context_directions():
    outgoing = call_history.HistoryCall(
        started_at=datetime(2026, 9, 1, 10, 0, 0),
        direction="out",
        remote_phone="79991000001",
    )
    incoming = call_history.HistoryCall(
        started_at=datetime(2026, 9, 1, 11, 0, 0),
        direction="in",
        remote_phone="79991000002",
    )

    ctx = call_history.call_context(outgoing, "79991234567", window=30)
    assert ctx["phone_a"] == "79991234567"
    assert ctx["phone_b"] == "79991000001"
    assert ctx["msisdn"] == "79991234567"
    assert ctx["tz"] == "Europe/Moscow"
    assert ctx["window"] == 30
    assert ctx["event_datetimes"] == [datetime(2026, 9, 1, 10, 0, 0)]

    ctx = call_history.call_context(incoming, "79991234567")
    assert ctx["phone_a"] == "79991000002"
    assert ctx["phone_b"] == "79991234567"

    ctx = call_history.call_context(incoming, None)
    assert ctx["phone_a"] == "79991000002"
    assert ctx["phone_b"] is None
    assert ctx["msisdn"] is None


def test_run_call_history_builds_links_per_call():
    result = gtool.run_call_history(
        HISTORY_SAMPLE,
        msisdn="79991234567",
        open_arg="zapis",
        window=60,
    )

    assert result.status == "success"
    assert result.total_calls == 6
    assert len(result.entries) == 6
    assert result.msisdn == "79991234567"
    # Предупреждения о номере клиента и усечении не ожидаем; возможен только
    # отказ Loki по давним датам фикстуры.
    assert not any(
        "Номер клиента" in warning or "Показаны первые" in warning
        for warning in result.warnings
    )

    first = result.entries[0]
    assert first.call.remote_phone == "79991000001"
    assert first.call.direction == "out"
    assert first.links_by_module["zapis"]
    link = first.links_by_module["zapis"][0]
    assert "var-phone=9991234567" in link
    assert "var-second_phone=9991000001" in link

    forwarded_links = next(
        entry.links_by_module["zapis"]
        for entry in result.entries
        if entry.call.remote_phone == "0900"
    )
    assert "var-phone=0900" in forwarded_links[0]
    assert "var-second_phone=9991234567" in forwarded_links[0]


def test_run_call_history_truncates_and_warns_without_msisdn():
    result = gtool.run_call_history(
        HISTORY_SAMPLE,
        msisdn=None,
        open_arg="zapis",
        max_calls=2,
    )

    assert result.total_calls == 6
    assert result.truncated
    assert len(result.entries) == 2
    assert any("Показаны первые 2" in warning for warning in result.warnings)
    assert any("Номер клиента не указан" in warning for warning in result.warnings)


def test_run_call_history_rejects_bad_input():
    try:
        gtool.run_call_history("обычный текст заявки без событий", open_arg="zapis")
    except ValueError as error:
        assert "Не удалось распознать" in str(error)
    else:
        raise AssertionError("expected ValueError")

    try:
        gtool.run_call_history(HISTORY_SAMPLE, msisdn="0900", open_arg="zapis")
    except ValueError as error:
        assert "некорректно" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_cli_prints_links_per_call(monkeypatch, tmp_path, capsys):
    history_path = tmp_path / "calls.txt"
    history_path.write_text(HISTORY_SAMPLE, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "call_history.py",
            "--file",
            str(history_path),
            "--msisdn",
            "79991234567",
            "--open",
            "zapis",
        ],
    )

    exit_code = call_history_cli.main()

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Распознано звонков: 6" in output
    assert "Переадресаций: 2" in output
    assert output.count("[Grafana / find-call-in-logs]") == 6
    assert "var-phone=9991234567" in output


def test_web_call_history_route_builds_per_call_links():
    response = webapp_request(
        "POST",
        "/call-history",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product": "recording",
            "window": "60",
            "msisdn": "79991234567",
            "history_text": HISTORY_SAMPLE,
        },
    )

    assert response.status_code == 200
    assert "История звонков из баланса" in response.text
    assert 'id="calls-result"' in response.text
    assert "Распознано звонков: <strong>6</strong>" in response.text
    assert "переадресация «занято» → 79991230002" in response.text
    assert "входящий ← 0900" in response.text
    assert 'class="call-item"' in response.text
    assert "var-phone=0900" in response.text
    # Бейджа «Секретарь» нет: номера Секретаря не настроены.
    assert 'call-badge">Секретарь' not in response.text


def test_web_call_history_route_validates_input():
    empty = webapp_request(
        "POST",
        "/call-history",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product": "recording",
            "history_text": "",
        },
    )
    assert empty.status_code == 400
    assert "Вставьте историю звонков" in empty.text

    bad_msisdn = webapp_request(
        "POST",
        "/call-history",
        data={
            "csrf_token": webapp.app.state.csrf_token,
            "product": "recording",
            "msisdn": "123",
            "history_text": HISTORY_SAMPLE,
        },
    )
    assert bad_msisdn.status_code == 400
    assert "Номер клиента указан некорректно" in bad_msisdn.text


def webapp_request(method, path, **kwargs):
    import asyncio

    import httpx

    def send():
        transport = httpx.ASGITransport(app=webapp.app)

        async def run():
            async with httpx.AsyncClient(
                transport=transport, base_url="http://localhost"
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(run())

    return send()


def test_example_file_from_docs_parses():
    example = Path(__file__).resolve().parents[1] / "examples" / "balance_history.example.txt"
    calls = call_history.parse_call_history(example.read_text(encoding="utf-8"))

    assert len(calls) == 38
    assert sum(1 for call in calls if call.forwarded) == 8
    # Номер клиента не передан — выводится по частоте участия.
    assert sum(1 for call in calls if call.direction == "out") == 15
    assert sum(1 for call in calls if call.direction == "in") == 23
