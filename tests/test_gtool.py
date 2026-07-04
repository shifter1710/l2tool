from types import SimpleNamespace
from datetime import datetime
import json
from zoneinfo import ZoneInfo

import gtool
import pytest
from core import parser
from gtool import format_event_time, format_links, format_opensearch_periods, format_parsed_context, format_phone_normalization


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
        "Найдена только дата события: 2026-05-04, поиск за весь день",
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
    assert format_links({"zapis": ["https://example.test/a"], "bff": ["https://example.test/b"]}) == [
        "[Grafana / find-call-in-logs]",
        "https://example.test/a",
        "[BFF / OpenSearch]",
        "https://example.test/b",
    ]


def test_resolve_modules_accepts_known_modules():
    assert gtool.resolve_modules("zapis,bff") == ["zapis", "bff"]


def test_resolve_modules_rejects_unknown_module():
    with pytest.raises(
        ValueError,
        match="Unknown module: bad. Available: zapis, sip_stack, bff, myconnect, myconnect_call",
    ):
        gtool.resolve_modules("bad")


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


def test_cli_main_prints_generated_links(monkeypatch, tmp_path, capsys):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text("Номер клиента (msisdn): +7 (999) 123-45-67", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(gtool.MODULES, "dummy", SimpleNamespace(build=lambda ctx: ["https://example.test/logs"]))
    monkeypatch.setattr(
        "sys.argv",
        ["gtool.py", "--file", str(ticket_path), "--open", "dummy"],
    )

    gtool.main()

    assert "https://example.test/logs" in capsys.readouterr().out


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


def test_cli_menu_selection_uses_recording(monkeypatch, tmp_path, capsys):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text("Номер клиента (msisdn): +7 (999) 123-45-67", encoding="utf-8")
    selected_open_args = []

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "1")
    monkeypatch.setattr("sys.argv", ["gtool.py", "--file", str(ticket_path)])
    monkeypatch.setattr(
        gtool,
        "run_ticket",
        lambda text, open_arg, window: selected_open_args.append(open_arg)
        or SimpleNamespace(lines=["generated"], links_by_module={}),
    )

    gtool.main()

    assert "1. Запись" in capsys.readouterr().out
    assert selected_open_args == ["zapis,sip_stack,bff"]


def test_cli_product_skips_input(monkeypatch, tmp_path):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text("Номер клиента (msisdn): +7 (999) 123-45-67", encoding="utf-8")
    selected_open_args = []

    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("input should not be called"))
    monkeypatch.setattr("sys.argv", ["gtool.py", "--file", str(ticket_path), "--product", "recording"])
    monkeypatch.setattr(
        gtool,
        "run_ticket",
        lambda text, open_arg, window: selected_open_args.append(open_arg)
        or SimpleNamespace(lines=["generated"], links_by_module={}),
    )

    gtool.main()

    assert selected_open_args == ["zapis,sip_stack,bff"]


def test_cli_open_skips_input(monkeypatch, tmp_path):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text("Номер клиента (msisdn): +7 (999) 123-45-67", encoding="utf-8")
    selected_open_args = []

    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("input should not be called"))
    monkeypatch.setattr("sys.argv", ["gtool.py", "--file", str(ticket_path), "--open", "bff"])
    monkeypatch.setattr(
        gtool,
        "run_ticket",
        lambda text, open_arg, window: selected_open_args.append(open_arg)
        or SimpleNamespace(lines=["generated"], links_by_module={}),
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
    monkeypatch.setattr(
        gtool,
        "run_ticket",
        lambda text, open_arg, window: selected_open_args.append(open_arg)
        or SimpleNamespace(lines=["generated"], links_by_module={}),
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
        lambda text, open_arg, window: SimpleNamespace(
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
        lambda text, open_arg, window: selected_open_args.append(open_arg)
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
        lambda text, open_arg, window: SimpleNamespace(
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
        lambda text, open_arg, window: selected_open_args.append(open_arg)
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
        lambda text, open_arg, window: SimpleNamespace(lines=["generated"], links_by_module={}),
    )

    gtool.main()

    assert not export_path.exists()
