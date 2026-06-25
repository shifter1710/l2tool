from types import SimpleNamespace

import gtool
import pytest
from core import parser
from gtool import format_event_time, format_opensearch_periods, format_parsed_context, format_phone_normalization


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


def test_format_opensearch_periods():
    assert format_opensearch_periods(["zapis", "bff", "myconnect", "myconnect_call"]) == [
        "OpenSearch: период поиска с now-1M по now",
        "OpenSearch: период поиска с now-2M по now",
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
