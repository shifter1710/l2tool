import json
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID

import gtool
from core import history


def dummy_module(urls=None, calls=None):
    urls = urls or ["https://example.test/logs"]

    def build(ctx):
        if calls is not None:
            calls.append(ctx)
        return urls

    return SimpleNamespace(build=build)


def test_ticket_numbers_includes_all_participants():
    ctx = {
        "msisdn": "79990000000",
        "phone_a": "79111111111",
        "phone_a_values": ["79111111111", "79222222222"],
        "phone_b": "79333333333",
        "phone_b_values": ["79333333333", "79444444444"],
    }

    assert history.ticket_numbers(ctx) == [
        "79990000000",
        "79111111111",
        "79222222222",
        "79333333333",
        "79444444444",
    ]


def test_run_ticket_prints_history_matches_without_saving(monkeypatch, tmp_path):
    ticket = "Номер клиента (msisdn): +7 (999) 123-45-67"
    history_dir = tmp_path / "history"
    saved_path = "history/2026/05/2026-05-06_79991234567_a1b2c3d4.yaml"
    history_dir.mkdir()
    (history_dir / "index.json").write_text(
        json.dumps({"79991234567": [saved_path]}),
        encoding="utf-8",
    )

    monkeypatch.setitem(gtool.MODULES, "dummy", dummy_module())
    result = gtool.run_ticket(
        ticket,
        open_arg="dummy",
        history_root=history_dir,
    )

    output = "\n".join(result.lines)
    assert "--- History matches ---" in output
    assert "79991234567:" in output
    assert f"  - {saved_path}" in output
    assert "History saved:" not in output
    assert not list(history_dir.rglob("*.yaml"))


def test_run_ticket_treats_corrupted_index_as_no_matches(monkeypatch, tmp_path):
    ticket = "Номер клиента (msisdn): +7 (999) 123-45-67"
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "index.json").write_text('{"79991234567": [', encoding="utf-8")

    monkeypatch.setitem(gtool.MODULES, "dummy", dummy_module())
    result = gtool.run_ticket(
        ticket,
        open_arg="dummy",
        history_root=history_dir,
    )

    output = "\n".join(result.lines)
    assert "--- History matches ---" in output
    assert "No matches" in output


def test_run_ticket_does_not_parse_existing_history_yaml(monkeypatch, tmp_path):
    ticket = "Номер клиента (msisdn): +7 (999) 123-45-67"
    history_dir = tmp_path / "history"
    archive_path = history_dir / "2026" / "05" / "partial.yaml"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_text("uuid: unfinished\nraw_ticket: |\n  broken", encoding="utf-8")
    (history_dir / "index.json").write_text(
        json.dumps({"79991234567": [archive_path.as_posix()]}),
        encoding="utf-8",
    )

    monkeypatch.setitem(gtool.MODULES, "dummy", dummy_module())
    result = gtool.run_ticket(
        ticket,
        open_arg="dummy",
        history_root=history_dir,
    )

    output = "\n".join(result.lines)
    assert archive_path.as_posix() in output


def test_run_ticket_saves_history_yaml_and_updates_index(monkeypatch, tmp_path):
    ticket = """Номер клиента (msisdn): +7 (999) 123-45-67
Номер звонящего (А): 3912777454
Номер принимающего звонок (Б): 83912777455
Дата и время проблемного звонка: 06.05.2026 10:30
Регион: Красноярск
"""
    calls = []
    history_dir = tmp_path / "history"

    monkeypatch.setattr(
        gtool,
        "MODULES",
        {
            "dummy": dummy_module(
                ["https://example.test/one", "https://example.test/two"],
                calls=calls,
            )
        },
    )
    monkeypatch.setattr(
        history,
        "uuid4",
        lambda: UUID("12345678-1234-5678-1234-567812345678"),
    )

    result = gtool.run_ticket(
        ticket,
        open_arg="dummy",
        input_file="tickets/current.txt",
        save_history=True,
        history_root=history_dir,
    )

    assert len(calls) == 1
    archive_path = (
        history_dir
        / "2026"
        / "05"
        / "2026-05-06_79991234567_12345678.yaml"
    )
    assert archive_path.exists()
    archive = archive_path.read_text(encoding="utf-8")
    assert 'uuid: "12345678-1234-5678-1234-567812345678"' in archive
    assert 'input_file: "tickets/current.txt"' in archive
    assert '  msisdn: "79991234567"' in archive
    assert '  phone_a: "73912777454"' in archive
    assert '  phone_b: "73912777455"' in archive
    assert '  timezone: "Asia/Krasnoyarsk"' in archive
    assert "modules:\n  - dummy" in archive
    assert '    - "https://example.test/one"' in archive
    assert '    - "https://example.test/two"' in archive
    assert "raw_ticket: |" in archive
    assert "History saved:" in "\n".join(result.lines)

    indexed = json.loads((history_dir / "index.json").read_text(encoding="utf-8"))
    archive_text_path = archive_path.as_posix()
    assert indexed == {
        "73912777454": [archive_text_path],
        "73912777455": [archive_text_path],
        "79991234567": [archive_text_path],
    }
    assert not list(history_dir.rglob("*.tmp"))


def test_cli_no_history_does_not_save_but_opens_links(monkeypatch, tmp_path, capsys):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text("Номер клиента (msisdn): +7 (999) 123-45-67", encoding="utf-8")
    opened = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(gtool.MODULES, "dummy", dummy_module())
    monkeypatch.setattr(gtool, "open_links", lambda links: opened.append(links))
    monkeypatch.setattr(
        "sys.argv",
        ["gtool.py", "--file", str(ticket_path), "--open", "dummy", "--no-history"],
    )

    gtool.main()

    output = capsys.readouterr().out
    assert "--- History matches ---" in output
    assert "No matches" in output
    assert "History saved:" not in output
    assert not (tmp_path / "history").exists()
    assert opened == [{"dummy": ["https://example.test/logs"]}]


def test_cli_normal_run_saves_history_and_opens_links(monkeypatch, tmp_path, capsys):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text(
        "\n".join(
            [
                "Номер клиента (msisdn): +7 (999) 123-45-67",
                "Дата и время проблемного звонка: 06.05.2026 10:30",
            ]
        ),
        encoding="utf-8",
    )
    opened = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(gtool.MODULES, "dummy", dummy_module())
    monkeypatch.setattr(gtool, "open_links", lambda links: opened.append(links))
    monkeypatch.setattr(
        history,
        "uuid4",
        lambda: UUID("12345678-1234-5678-1234-567812345678"),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["gtool.py", "--file", str(ticket_path), "--open", "dummy"],
    )

    gtool.main()

    output = capsys.readouterr().out
    archive_path = (
        tmp_path
        / "history"
        / "2026"
        / "05"
        / "2026-05-06_79991234567_12345678.yaml"
    )
    assert "History saved:" in output
    assert archive_path.exists()
    assert (tmp_path / "history" / "index.json").exists()
    assert opened == [{"dummy": ["https://example.test/logs"]}]


def test_cli_dry_run_does_not_save_or_open(monkeypatch, tmp_path, capsys):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text("Номер клиента (msisdn): +7 (999) 123-45-67", encoding="utf-8")
    opened = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(gtool.MODULES, "dummy", dummy_module())
    monkeypatch.setattr(gtool, "open_links", lambda links: opened.append(links))
    monkeypatch.setattr(
        "sys.argv",
        ["gtool.py", "--file", str(ticket_path), "--open", "dummy", "--dry-run"],
    )

    gtool.main()

    output = capsys.readouterr().out
    assert "https://example.test/logs" in output
    assert "History saved:" not in output
    assert not (tmp_path / "history").exists()
    assert opened == []


def test_cli_dry_run_does_not_write_parser_diagnostics(monkeypatch, tmp_path, capsys):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text("Номер клиента (msisdn): 14951234567", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(gtool.MODULES, "dummy", dummy_module())
    monkeypatch.setattr(gtool, "open_links", lambda links: None)
    monkeypatch.setattr(
        "sys.argv",
        ["gtool.py", "--file", str(ticket_path), "--open", "dummy", "--dry-run"],
    )

    gtool.main()

    assert "[WARN] Проблема парсинга:" in capsys.readouterr().out
    assert not (tmp_path / "parser_issues").exists()


def test_save_history_uses_current_date_when_ticket_has_no_event_time(tmp_path):
    ctx = {
        "msisdn": None,
        "phone_a": None,
        "phone_b": None,
        "event_time": None,
        "event_date": None,
        "region": None,
        "tz": "Europe/Moscow",
    }

    archive_path = history.save_ticket_history(
        ctx=ctx,
        input_file="tickets/current.txt",
        raw_ticket="plain text",
        links_by_module={},
        history_root=tmp_path / "history",
        now=datetime(2026, 5, 7, 12, 0),
        uuid_factory=lambda: UUID("87654321-4321-8765-4321-876543218765"),
    )

    assert archive_path.name == "2026-05-07_unknown_87654321.yaml"
