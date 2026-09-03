import json
import re
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import gtool
from core import parser
from gtool import (
    format_event_time,
    format_links,
    format_opensearch_periods,
    format_parsed_context,
    format_phone_normalization,
    terminal_link,
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

    assert gtool.format_loki_retention_warning(
        ctx,
        now=datetime(2026, 5, 10, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
    ) == [
        "[WARN] Loki хранит логи только 5 дней. По Grafana/Loki данные могут быть уже недоступны."
    ]


def test_format_loki_retention_warning_for_recent_date():
    ctx = parser.parse("Дата проблемного звонка: 04.05.2026")
    ctx["tz"] = "Europe/Moscow"

    assert gtool.format_loki_retention_warning(
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
    assert gtool.resolve_modules("zapis,bff") == ["zapis", "bff"]


def test_resolve_modules_removes_duplicates_without_reordering():
    assert gtool.resolve_modules("bff,zapis,bff") == ["bff", "zapis"]


def test_resolve_modules_rejects_unknown_module():
    expected = re.escape(
        "Unknown service: bad. Available: "
        "zapis, sip_stack, bff, secretary, myconnect, myconnect_call, noise"
        ", recording_mgw, recording_vss_crs, recording_crs, recording_collector"
    )
    with pytest.raises(ValueError, match=expected):
        gtool.resolve_modules("bad")


def test_default_open_matches_issue_workflow():
    assert gtool.DEFAULT_OPEN == "zapis,bff,myconnect,myconnect_call"


def test_default_grafana_window_is_one_hour():
    assert gtool.DEFAULT_WINDOW == 60


def test_prompt_parse_fixes_requests_only_problem_fields():
    prompts = []
    answers = iter(["79991112233", "04.05.2026 12:30"])
    issues = [
        {"field": "phone_a", "message": "Номер А не распознан"},
        {"field": "event_datetime", "message": "Дата не распознана"},
    ]

    repaired = gtool.prompt_parse_fixes(
        "Исходный тикет",
        issues,
        input_fn=lambda prompt: prompts.append(prompt) or next(answers),
    )

    assert prompts == [
        "Введите Номер А (Enter — оставить пустым): ",
        "Введите Дата и время звонка (Enter — пропустить): ",
    ]
    assert repaired == (
        "Номер звонящего (А): 79991112233\n"
        "Дата и время проблемного звонка: 04.05.2026 12:30\n"
        "Исходный тикет"
    )


def test_prompt_parse_fixes_allows_empty_phone():
    text = """Номер клиента (msisdn): 79990000000
Номер звонящего (А): скрыт оператором
Дата и время проблемного звонка: 28.08.2026 12:00
"""
    issues = gtool.collect_parse_issues(text, parser.parse(text))

    repaired = gtool.prompt_parse_fixes(text, issues, input_fn=lambda _prompt: "")
    repaired_ctx = parser.parse(repaired)

    assert repaired.startswith("Номер звонящего (А): нет\n")
    assert repaired_ctx["phone_a"] is None
    assert gtool.collect_parse_issues(repaired, repaired_ctx) == []


def test_prompt_parse_fixes_allows_skipping_bad_event_time():
    text = """Номер клиента (msisdn): 79990000000
Дата и время проблемного звонка: время неизвестно
"""
    issues = gtool.collect_parse_issues(text, parser.parse(text))

    repaired = gtool.prompt_parse_fixes(text, issues, input_fn=lambda _prompt: "")
    repaired_ctx = parser.parse(repaired)

    assert repaired.startswith("Дата и время проблемного звонка: пропустить\n")
    assert repaired_ctx["event_time"] is None
    assert gtool.collect_parse_issues(repaired, repaired_ctx) == []

    result = gtool.run_ticket(
        text,
        open_arg="zapis,bff",
        parse_text=repaired,
        write_diagnostics=False,
    )
    assert set(result.links_by_module) == {"zapis", "bff"}


def test_prompt_date_only_window_keeps_default_when_empty():
    text = "Дата проблемного звонка: 04.05.2026"
    ctx = parser.parse(text)

    assert gtool.is_date_only_context(ctx) is True
    assert gtool.prompt_date_only_window(text, ctx, input_fn=lambda prompt: "") == text


def test_prompt_date_only_window_uses_entered_datetime():
    text = "Дата проблемного звонка: 04.05.2026"
    ctx = parser.parse(text)

    repaired = gtool.prompt_date_only_window(
        text,
        ctx,
        input_fn=lambda prompt: "05.05.2026 12:30",
    )
    repaired_ctx = parser.parse(repaired)

    assert str(repaired_ctx["event_time"]) == "2026-05-05 12:30:00"


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
        gtool.MODULES,
        "dummy",
        SimpleNamespace(build=lambda ctx: ["https://example.test/logs"]),
    )
    result = gtool.run_ticket(
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


def test_cli_main_prints_generated_links(monkeypatch, tmp_path, capsys):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text(
        "Номер клиента (msisdn): +7 (999) 123-45-67\n"
        "Дата и время проблемного звонка: 06.05.2026 10:30",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(gtool.MODULES, "dummy", SimpleNamespace(build=lambda ctx: ["https://example.test/logs"]))
    monkeypatch.setattr(gtool, "open_links", lambda links: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "gtool.py",
            "--file",
            str(ticket_path),
            "--open",
            "dummy",
            "--no-history",
        ],
    )

    gtool.main()

    assert "https://example.test/logs" in capsys.readouterr().out


def test_cli_interactively_repairs_parse_error_before_building_links(
    monkeypatch, tmp_path, capsys
):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text(
        "Номер клиента (msisdn): 14951234567\nДата и время проблемного звонка: 06.05.2026 10:30",
        encoding="utf-8",
    )
    calls = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(
        gtool.MODULES,
        "dummy",
        SimpleNamespace(build=lambda ctx: calls.append(ctx) or ["https://example.test/logs"]),
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "79991234567")
    monkeypatch.setattr(
        "sys.argv",
        ["gtool.py", "--file", str(ticket_path), "--open", "dummy", "--no-history"],
    )

    gtool.main()

    output = capsys.readouterr().out
    assert "[ERROR] Номер клиента не распознан: 14951234567" in output
    assert "Строка 1: Номер клиента (msisdn): 14951234567" in output
    assert "https://example.test/logs" in output
    assert calls[0]["msisdn"] == "79991234567"


def test_cli_missing_default_ticket_reports_error(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["gtool.py"])

    with pytest.raises(SystemExit):
        gtool.main()

    assert "ticket file not found: tickets/current.txt" in capsys.readouterr().err


def test_cli_product_and_open_together_error(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["gtool.py", "--product", "recording", "--open", "zapis"])

    with pytest.raises(SystemExit):
        gtool.main()

    assert "Use either --product or --open, not both" in capsys.readouterr().err


def test_cli_product_bff_is_not_allowed(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["gtool.py", "--product", "bff"])

    with pytest.raises(SystemExit):
        gtool.main()

    assert "invalid choice: 'bff'" in capsys.readouterr().err


def test_cli_product_without_services_returns_failed_exit(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["gtool.py", "--product", "assistant"])

    exit_code = gtool.main()

    assert exit_code == 2
    assert "пока нет настроенных сервисов" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("choice", "expected_open_arg"),
    [
        ("1", "zapis,sip_stack,bff"),
        ("2", "secretary"),
        ("3", "myconnect,myconnect_call"),
        ("4", "noise"),
    ],
)
def test_cli_plain_run_prompts_for_product(
    monkeypatch,
    tmp_path,
    choice,
    expected_open_arg,
):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text("Номер клиента (msisdn): +7 (999) 123-45-67", encoding="utf-8")
    selected_open_args = []

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: choice)
    monkeypatch.setattr("sys.argv", ["gtool.py", "--file", str(ticket_path)])
    monkeypatch.setattr(gtool, "open_links", lambda links: None)
    monkeypatch.setattr(
        gtool,
        "run_ticket",
        lambda text, open_arg, window, **kwargs: selected_open_args.append(open_arg)
        or SimpleNamespace(ctx={}, selected_modules=[], lines=["generated"], links_by_module={}),
    )

    gtool.main()

    assert selected_open_args == [expected_open_arg]


def test_cli_product_skips_input(monkeypatch, tmp_path):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text("Номер клиента (msisdn): +7 (999) 123-45-67", encoding="utf-8")
    selected_open_args = []

    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("input should not be called"))
    monkeypatch.setattr(
        "sys.argv",
        ["gtool.py", "--file", str(ticket_path), "--product", "recording"],
    )
    monkeypatch.setattr(gtool, "open_links", lambda links: None)
    monkeypatch.setattr(
        gtool,
        "run_ticket",
        lambda text, open_arg, window, **kwargs: selected_open_args.append(open_arg)
        or SimpleNamespace(ctx={}, selected_modules=[], lines=["generated"], links_by_module={}),
    )

    gtool.main()

    assert selected_open_args == ["zapis,sip_stack,bff"]


def test_cli_open_skips_input(monkeypatch, tmp_path):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text("Номер клиента (msisdn): +7 (999) 123-45-67", encoding="utf-8")
    selected_open_args = []

    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("input should not be called"))
    monkeypatch.setattr("sys.argv", ["gtool.py", "--file", str(ticket_path), "--open", "bff"])
    monkeypatch.setattr(gtool, "open_links", lambda links: None)
    monkeypatch.setattr(
        gtool,
        "run_ticket",
        lambda text, open_arg, window, **kwargs: selected_open_args.append(open_arg)
        or SimpleNamespace(ctx={}, selected_modules=[], lines=["generated"], links_by_module={}),
    )

    gtool.main()

    assert selected_open_args == ["bff"]


def test_cli_non_interactive_stdin_uses_default_open(monkeypatch, tmp_path):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text("Номер клиента (msisdn): +7 (999) 123-45-67", encoding="utf-8")
    selected_open_args = []

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("input should not be called"))
    monkeypatch.setattr("sys.argv", ["gtool.py", "--file", str(ticket_path)])
    monkeypatch.setattr(gtool, "open_links", lambda links: None)
    monkeypatch.setattr(
        gtool,
        "run_ticket",
        lambda text, open_arg, window, **kwargs: selected_open_args.append(open_arg)
        or SimpleNamespace(ctx={}, selected_modules=[], lines=["generated"], links_by_module={}),
    )

    gtool.main()

    assert selected_open_args == [gtool.DEFAULT_OPEN]


def test_cli_product_exports_case_json(monkeypatch, tmp_path, capsys):
    ticket_path = tmp_path / "tickets" / "current.txt"
    ticket_path.parent.mkdir()
    ticket_path.write_text("Номер клиента (msisdn): +7 (999) 123-45-67", encoding="utf-8")
    export_path = tmp_path / "cases" / "current.json"
    ctx = {
        "msisdn": "79991234567",
        "phone_a": None,
        "phone_b": None,
        "event_date": datetime(2026, 5, 4, 10, 49).date(),
        "event_time": datetime(2026, 5, 4, 10, 49),
        "event_datetimes": [datetime(2026, 5, 4, 10, 49)],
        "tz": "Europe/Moscow",
        "window": 120,
        "region": None,
    }

    monkeypatch.setattr(
        "sys.argv",
        [
            "gtool.py",
            "--file",
            str(ticket_path),
            "--product",
            "recording",
            "--export-case",
            str(export_path),
        ],
    )
    monkeypatch.setattr(
        gtool,
        "run_ticket",
        lambda text, open_arg, window, **kwargs: SimpleNamespace(
            ctx=ctx,
            selected_modules=["zapis", "sip_stack", "bff"],
            links_by_module={"zapis": ["https://example.test"]},
            lines=["generated"],
        ),
    )

    gtool.main()

    data = json.loads(export_path.read_text(encoding="utf-8"))
    assert data["product"] == "recording"
    assert data["source"]["file_name"] == "current.txt"
    assert data["event"]["time"] == "2026-05-04T10:49:00+03:00"
    assert "Case JSON saved to: " + str(export_path) in capsys.readouterr().out


def test_cli_interactive_product_exports_selected_product(monkeypatch, tmp_path):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text("Номер клиента (msisdn): +7 (999) 123-45-67", encoding="utf-8")
    export_path = tmp_path / "cases" / "current.json"
    selected_open_args = []

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "1")
    monkeypatch.setattr(
        "sys.argv",
        [
            "gtool.py",
            "--file",
            str(ticket_path),
            "--export-case",
            str(export_path),
        ],
    )
    monkeypatch.setattr(
        gtool,
        "run_ticket",
        lambda text, open_arg, window, **kwargs: selected_open_args.append(open_arg)
        or SimpleNamespace(
            ctx={"tz": "Europe/Moscow", "window": 120, "event_datetimes": []},
            selected_modules=["zapis", "sip_stack", "bff"],
            links_by_module={},
            lines=["generated"],
        ),
    )

    gtool.main()

    data = json.loads(export_path.read_text(encoding="utf-8"))
    assert data["product"] == "recording"
    assert selected_open_args == ["zapis,sip_stack,bff"]


def test_cli_ignores_saved_case_and_always_starts_new(monkeypatch, tmp_path):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text(
        "Номер клиента (msisdn): +7 (999) 123-45-67",
        encoding="utf-8",
    )
    ticket_path.with_name("ticket.parsed.json").write_text(
        json.dumps({"product": "recording"}),
        encoding="utf-8",
    )
    prompts = []
    answers = iter(["2", ""])

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: prompts.append(prompt) or next(answers),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["gtool.py", "--file", str(ticket_path), "--dry-run"],
    )
    monkeypatch.setattr(
        gtool,
        "run_ticket",
        lambda text, open_arg, window, **kwargs: SimpleNamespace(
            ctx={}, selected_modules=[], lines=["generated"], links_by_module={}
        ),
    )

    gtool.main()

    assert prompts == [
        "Введите номер: ",
        "Введите Дата и время звонка (Enter — пропустить): ",
    ]


def test_cli_open_exports_case_json_with_null_product(monkeypatch, tmp_path):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text("Номер клиента (msisdn): +7 (999) 123-45-67", encoding="utf-8")
    export_path = tmp_path / "cases" / "current.json"

    monkeypatch.setattr(
        "sys.argv",
        [
            "gtool.py",
            "--file",
            str(ticket_path),
            "--open",
            "bff",
            "--export-case",
            str(export_path),
        ],
    )
    monkeypatch.setattr(
        gtool,
        "run_ticket",
        lambda text, open_arg, window, **kwargs: SimpleNamespace(
            ctx={"tz": "Europe/Moscow", "window": 120, "event_datetimes": []},
            selected_modules=["bff"],
            links_by_module={},
            lines=["generated"],
        ),
    )

    gtool.main()

    data = json.loads(export_path.read_text(encoding="utf-8"))
    assert data["product"] is None
    assert data["search"]["selected_modules"] == ["bff"]


def test_cli_non_interactive_default_export_has_null_product(monkeypatch, tmp_path):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text("Номер клиента (msisdn): +7 (999) 123-45-67", encoding="utf-8")
    export_path = tmp_path / "cases" / "current.json"
    selected_open_args = []

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("input should not be called"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "gtool.py",
            "--file",
            str(ticket_path),
            "--export-case",
            str(export_path),
        ],
    )
    monkeypatch.setattr(
        gtool,
        "run_ticket",
        lambda text, open_arg, window, **kwargs: selected_open_args.append(open_arg)
        or SimpleNamespace(
            ctx={"tz": "Europe/Moscow", "window": 120, "event_datetimes": []},
            selected_modules=["zapis", "sip_stack", "bff", "myconnect", "myconnect_call"],
            links_by_module={},
            lines=["generated"],
        ),
    )

    gtool.main()

    data = json.loads(export_path.read_text(encoding="utf-8"))
    assert data["product"] is None
    assert selected_open_args == [gtool.DEFAULT_OPEN]


def test_cli_without_export_case_does_not_create_json(monkeypatch, tmp_path):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text("Номер клиента (msisdn): +7 (999) 123-45-67", encoding="utf-8")
    export_path = tmp_path / "cases" / "current.json"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["gtool.py", "--file", str(ticket_path), "--open", "bff"])
    monkeypatch.setattr(
        gtool,
        "run_ticket",
        lambda text, open_arg, window, **kwargs: SimpleNamespace(
            ctx={}, selected_modules=[], lines=["generated"], links_by_module={}
        ),
    )

    gtool.main()

    assert not export_path.exists()
    sidecar_path = ticket_path.with_name("ticket.parsed.json")
    assert sidecar_path.exists()
    assert json.loads(sidecar_path.read_text(encoding="utf-8"))["identifiers"]["call_uuid"] == ""


def test_cli_failed_parse_preserves_existing_sidecar_and_skips_export(
    monkeypatch,
    tmp_path,
    capsys,
):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text(
        "Номер клиента (msisdn): 123\nДата и время проблемного звонка: неверно",
        encoding="utf-8",
    )
    sidecar_path = ticket_path.with_name("ticket.parsed.json")
    sidecar_path.write_text('{"previous": true}\n', encoding="utf-8")
    export_path = tmp_path / "case.json"

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "gtool.py",
            "--file",
            str(ticket_path),
            "--open",
            "bff",
            "--export-case",
            str(export_path),
            "--no-history",
        ],
    )

    exit_code = gtool.main()

    assert exit_code == 2
    assert sidecar_path.read_text(encoding="utf-8") == '{"previous": true}\n'
    assert not export_path.exists()
    output = capsys.readouterr().out
    assert "Parsed case not saved" in output
    assert "Case JSON not saved" in output


def test_run_ticket_rejects_invalid_call_uuid(monkeypatch):
    monkeypatch.setitem(
        gtool.MODULES,
        "dummy",
        SimpleNamespace(build=lambda _ctx: ["https://example.test/logs"]),
    )

    with pytest.raises(ValueError, match="Некорректный UUID звонка"):
        gtool.run_ticket(
            """Номер клиента (msisdn): 79991234567
Дата и время проблемного звонка: 06.05.2026 10:30
""",
            open_arg="dummy",
            call_uuid='broken" |~ ".*"',
            write_diagnostics=False,
        )
