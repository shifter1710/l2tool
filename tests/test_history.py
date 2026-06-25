from types import SimpleNamespace

import gtool


def dummy_module():
    return SimpleNamespace(build=lambda ctx: ["https://example.test/logs"])


def run_dummy_ticket(monkeypatch, tmp_path, ticket, **kwargs):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(gtool.MODULES, "dummy", dummy_module())
    return gtool.run_ticket(ticket, open_arg="dummy", **kwargs)


def test_run_ticket_does_not_save_history_by_default(monkeypatch, tmp_path):
    ticket = "Номер клиента (msisdn): +7 (999) 123-45-67"

    result = run_dummy_ticket(monkeypatch, tmp_path, ticket)

    assert not (tmp_path / "history").exists()
    assert not list(tmp_path.rglob("*.yaml"))
    assert all("History" not in line for line in result.lines)


def test_run_ticket_does_not_write_yaml(monkeypatch, tmp_path):
    ticket = "Номер клиента (msisdn): +7 (999) 123-45-67"

    run_dummy_ticket(monkeypatch, tmp_path, ticket)

    assert not list(tmp_path.rglob("*.yaml"))


def test_cli_main_does_not_save_history(monkeypatch, tmp_path, capsys):
    ticket = "Номер клиента (msisdn): +7 (999) 123-45-67"
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text(ticket, encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(gtool.MODULES, "dummy", dummy_module())
    monkeypatch.setattr(
        "sys.argv",
        ["gtool.py", "--file", str(ticket_path), "--open", "dummy"],
    )

    gtool.main()

    output = capsys.readouterr().out
    assert "History saved:" not in output
    assert "History matches" not in output
    assert not (tmp_path / "history").exists()
    assert not list(tmp_path.rglob("*.yaml"))
