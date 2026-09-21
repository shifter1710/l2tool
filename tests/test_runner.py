import re
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from core import parser, runner
from core.dynamic_sources import save_source

PHONE_URL = (
    "https://dashboards.example.local/app/data-explorer/discover"
    "#?_a=(metadata:(indexPattern:custom-view),"
    "query:(language:kuery,query:'msisdn:79991234567'))"
    "&_g=(time:(from:'2026-09-03T11:00:00.000',to:'2026-09-03T12:00:00.000'))"
)


def add_number_block(name="Пользовательский BFF", product="recording", url=PHONE_URL):
    return save_source(
        {
            "name": name,
            "product": product,
            "level": "number",
            "example_url": url,
            "sample_value": "",
            "minutes_before": 2,
            "minutes_after": 90,
        }
    )


def test_format_loki_retention_warning_for_old_date():
    ctx = parser.parse("Дата проблемного звонка: 04.05.2026")
    ctx["tz"] = "Europe/Moscow"

    assert runner.format_loki_retention_warning(
        ctx,
        now=datetime(2026, 5, 10, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
    ) == [
        "[WARN] Loki хранит логи только 5 дней. "
        "По Grafana/Loki данные могут быть уже недоступны."
    ]


def test_format_loki_retention_warning_for_recent_date():
    ctx = parser.parse("Дата проблемного звонка: 04.05.2026")
    ctx["tz"] = "Europe/Moscow"

    assert runner.format_loki_retention_warning(
        ctx,
        now=datetime(2026, 5, 8, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
    ) == []


def test_resolve_modules_accepts_known_modules():
    assert runner.resolve_modules("zapis,bff") == ["zapis", "bff"]


def test_resolve_modules_removes_duplicates_without_reordering():
    assert runner.resolve_modules("bff,zapis,bff") == ["bff", "zapis"]


def test_resolve_modules_rejects_unknown_module():
    expected = re.escape(
        "Unknown service: bad. Available: "
        "zapis, sip_stack, bff, secretary, myconnect, myconnect_call, noise"
        ", recording_mgw, recording_vss_crs, recording_crs, recording_collector"
    )
    with pytest.raises(ValueError, match=expected):
        runner.resolve_modules("bad")


def test_default_open_matches_issue_workflow():
    assert runner.DEFAULT_OPEN == "zapis,bff,myconnect,myconnect_call"


def test_default_grafana_window_is_one_hour():
    assert runner.DEFAULT_WINDOW == 60


def test_run_ticket_builds_links_despite_issues_when_client_number_known():
    # «Номер А» в заявке — текст, не номер; номер клиента распознан,
    # поэтому диагностика строится, а проблема остаётся предупреждением.
    text = """Номер клиента (msisdn): 79992508883
Номер А: все номера в этот промежуток
Номер Б: 79992508883
Дата проблемного звонка: 04.05.2026
"""
    result = runner.run_ticket(
        text, open_arg="zapis"
    )

    assert list(result.links_by_module) == ["zapis"]
    assert result.status == "success"
    assert result.errors == []
    assert any(
        "Номер А не распознан: все номера в этот промежуток" in warning
        for warning in result.warnings
    )


def test_run_ticket_still_blocks_without_client_number():
    # Без номера клиента проблемы разбора блокируют построение ссылок.
    text = """Номер А: все номера в этот промежуток
Номер Б: 79991000001
Дата проблемного звонка: 04.05.2026
"""
    result = runner.run_ticket(
        text, open_arg="zapis"
    )

    assert result.status == "failed"
    assert result.links_by_module == {}
    assert result.errors == ["Номер А не распознан: все номера в этот промежуток"]


def test_run_ticket_uses_parse_text_override():
    # Правки полей из веб-формы приходят отдельным текстом: исходная
    # заявка сохраняется в историю как есть, разбор идёт по правкам.
    text = """Номер клиента (msisdn): 79990000000
Дата и время проблемного звонка: время неизвестно
"""
    repaired = "Дата и время проблемного звонка: пропустить\n" + text

    result = runner.run_ticket(
        text,
        open_arg="zapis,bff",
        parse_text=repaired,
    )
    assert set(result.links_by_module) == {"zapis", "bff"}


def test_run_ticket_partial_when_service_generated_no_links(monkeypatch):
    # Один сервис вернул ссылки, другой — нет: результат частичный.
    monkeypatch.setitem(
        runner.MODULES,
        "dummy",
        SimpleNamespace(build=lambda _ctx: ["https://example.test/logs"]),
    )
    monkeypatch.setitem(
        runner.MODULES,
        "empty",
        SimpleNamespace(build=lambda _ctx: []),
    )

    result = runner.run_ticket(
        """Номер клиента (msisdn): 79991234567
Дата и время проблемного звонка: 06.05.2026 10:30
""",
        open_arg="dummy,empty",
    )

    assert result.status == "partial"
    assert list(result.links_by_module) == ["dummy"]
    assert result.errors == ["[ERROR] Service generated no links: empty"]
    # Ошибка сборки не дублируется в warnings: событие живёт только в errors,
    # веб-слой показывает его один раз с префиксом «[ERROR] ».
    assert "Service generated no links: empty" not in result.warnings


def test_run_call_history_reads_service_catalog_once(monkeypatch):
    # 50 звонков должны обходиться одним чтением каталога сервисов,
    # а не одним чтением хранилища блоков на каждый звонок.
    entries = []
    for index in range(50):
        entries.append(f"08.09.2026 10:{index % 60:02d}:00-10:{index % 60:02d}:30 (0:00:30)")
        entries.append(f"79991234567 → 7999100{index:04d}")
        entries.append("")
    history_text = "\n".join(entries)

    calls = []
    original = runner.available_services

    def counting_available_services():
        calls.append(1)
        return original()

    monkeypatch.setattr(runner, "available_services", counting_available_services)

    result = runner.run_call_history(history_text, open_arg="zapis", msisdn="79991234567")

    assert result.status == "success"
    assert len(result.entries) == 50
    assert calls == [1]


def test_run_ticket_rejects_invalid_call_uuid(monkeypatch):
    monkeypatch.setitem(
        runner.MODULES,
        "dummy",
        SimpleNamespace(build=lambda _ctx: ["https://example.test/logs"]),
    )

    with pytest.raises(ValueError, match="Некорректный UUID звонка"):
        runner.run_ticket(
            """Номер клиента (msisdn): 79991234567
Дата и время проблемного звонка: 06.05.2026 10:30
""",
            open_arg="dummy",
            call_uuid='broken" |~ ".*"',
        )


def test_static_mode_without_store_resolves_static_modules():
    assert runner.enabled_dynamic_sources() == []
    assert runner.resolve_modules("zapis,bff") == ["zapis", "bff"]


def test_store_without_blocks_keeps_static_scheme(monkeypatch):
    from core import dynamic_sources

    dynamic_sources.write_store(
        {
            "version": 2,
            "products": [
                {"key": "recording", "title": "Запись", "color": None,
                 "builtin": True, "managed": True}
            ],
            "sources": [],
        }
    )

    assert runner.enabled_dynamic_sources() == []
    assert runner.managed_product_keys() == set()


def test_open_unknown_block_lists_available():
    block = add_number_block()

    with pytest.raises(ValueError) as error:
        runner.resolve_modules("нет-такого-блока")

    message = str(error.value)
    assert "Unknown service: нет-такого-блока" in message
    assert f"Пользовательский BFF ({block['id']})" in message
    assert "zapis" in message


def test_open_accepts_block_id_and_name():
    block = add_number_block()

    assert runner.resolve_modules(block["id"]) == [block["id"]]
    assert runner.resolve_modules("Пользовательский BFF") == [block["id"]]
