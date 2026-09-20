import re
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from core import parser, runner
from core.dynamic_sources import save_source
from core.runner import (
    format_event_time,
    format_links,
    format_opensearch_periods,
    format_parsed_context,
    format_phone_normalization,
    terminal_link,
)

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


def test_format_phone_b_normalization():
    ctx = parser.parse("Номер принимающего звонок (Б): 83912777454")

    assert "Номер Б нормализован: 83912777454 -> 73912777454" in format_phone_normalization(ctx)


def test_format_phone_a_not_set():
    ctx = parser.parse("Номер звонящего (А): любой")

    assert "Номер А не задан: любой" in format_phone_normalization(ctx)


def test_format_multiple_event_times():
    ctx = parser.parse("Дата и время проблемного звонка: 04.05.2026  10-49    11-01")

    assert format_event_time(ctx) == [
        "События звонков найдены: 2",
        "Найдено несколько времен события:",
        "- 2026-05-04 10:49:00",
        "- 2026-05-04 11:01:00",
    ]


def test_format_date_only_event_time():
    ctx = parser.parse("Дата проблемного звонка: 04.05.2026")

    assert format_event_time(ctx) == [
        "Найдена только дата события: 2026-05-04, поиск с 08:00 до 20:00",
    ]


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


def test_format_opensearch_periods():
    assert format_opensearch_periods(["zapis", "bff", "myconnect", "myconnect_call"]) == [
        "OpenSearch: период поиска с now-1M по now",
        "OpenSearch: период поиска с now-2M по now",
    ]


def test_format_links_uses_human_readable_titles():
    links = format_links({"zapis": ["https://example.test/a"], "bff": ["https://example.test/b"]})
    assert links == [
        "[Grafana / find-call-in-logs]",
        "\033]8;;https://example.test/a\033\\https://example.test/a\033]8;;\033\\",
        "[BFF / OpenSearch]",
        "\033]8;;https://example.test/b\033\\https://example.test/b\033]8;;\033\\",
    ]


def test_terminal_link_keeps_complex_url_unchanged():
    url = (
        "https://example.test/discover#?_g=(time:(from:'now-1h',to:now))"
        "&_q=(query:(query:foo!bar))"
    )

    rendered = terminal_link(url, url)

    assert rendered == f"\033]8;;{url}\033\\{url}\033]8;;\033\\"
    assert rendered.removeprefix("\033]8;;").split("\033\\", 1)[0] == url


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
        text, open_arg="zapis", write_diagnostics=False
    )

    assert list(result.links_by_module) == ["zapis"]
    assert result.status == "success"
    assert result.errors == []
    assert any(
        "Номер А не распознан: все номера в этот промежуток" in line
        for line in result.lines
    )


def test_run_ticket_still_blocks_without_client_number():
    # Без номера клиента проблемы разбора блокируют построение ссылок.
    text = """Номер А: все номера в этот промежуток
Номер Б: 79991000001
Дата проблемного звонка: 04.05.2026
"""
    result = runner.run_ticket(
        text, open_arg="zapis", write_diagnostics=False
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
        write_diagnostics=False,
    )
    assert set(result.links_by_module) == {"zapis", "bff"}


def test_format_parsed_context_omits_technical_duplicates():
    ctx = parser.parse("""Номер клиента (msisdn): +7 (999) 123-45-67
Номер принимающего звонок (Б): 83912777454
Дата и время проблемного звонка: 04.05.2026 10-49 11-01
""")
    ctx["tz"] = "Europe/Moscow"
    ctx["window"] = 120
    ctx["selected_modules"] = ["zapis", "bff"]

    output = "\n".join(format_parsed_context(ctx))

    assert "Номер клиента: 79991234567" in output
    assert "Номер Б: 73912777454" in output
    assert "Timezone: Europe/Moscow" in output
    assert "Window: 120" in output
    assert "selected_modules: zapis, bff" in output
    assert "msisdn_hash:" in output
    assert "event_datetimes:" not in output
    assert "number_b:" not in output
    assert "callee:" not in output
    assert "phone_fields:" not in output
    assert "normalized_phones:" not in output


def test_warnings_are_grouped_after_history_before_links(monkeypatch, tmp_path):
    monkeypatch.setitem(
        runner.MODULES,
        "dummy",
        SimpleNamespace(build=lambda ctx: ["https://example.test/logs"]),
    )
    result = runner.run_ticket(
        """Номер клиента (msisdn): 79991234567
Дата и время проблемного звонка: 04.05.2026 10:49
""",
        open_arg="dummy",
        history_root=tmp_path / "history",
        write_diagnostics=False,
    )

    parsed_end = result.lines.index("----------------------")
    history_end = result.lines.index("-----------------------")
    warning_header = result.lines.index("--- Warnings and errors ---")
    warning = next(
        index
        for index, line in enumerate(result.lines)
        if line.startswith("[WARN] Loki хранит логи")
    )
    links_header = result.lines.index("[dummy]")

    assert parsed_end < history_end < warning_header < warning < links_header


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
            write_diagnostics=False,
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
