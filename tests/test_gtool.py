from types import SimpleNamespace

import gtool
from core import parser
from gtool import print_event_time, print_opensearch_periods, print_phone_normalization


def test_print_phone_b_normalization(capsys):
    ctx = parser.parse("Номер принимающего звонок (Б): 83912777454")

    print_phone_normalization(ctx)

    assert "Номер Б нормализован: 83912777454 -> 73912777454" in capsys.readouterr().out


def test_print_phone_a_not_set(capsys):
    ctx = parser.parse("Номер звонящего (А): любой")

    print_phone_normalization(ctx)

    assert "Номер А не задан: любой" in capsys.readouterr().out


def test_print_multiple_event_times(capsys):
    ctx = parser.parse("Дата и время проблемного звонка: 04.05.2026  10-49    11-01")

    print_event_time(ctx)

    assert capsys.readouterr().out == (
        "События звонков найдены: 2\n"
        "Найдено несколько времен события:\n"
        "- 2026-05-04 10:49:00\n"
        "- 2026-05-04 11:01:00\n"
    )


def test_print_opensearch_periods(capsys):
    print_opensearch_periods(["zapis", "bff", "myconnect", "myconnect_call"])

    assert capsys.readouterr().out == (
        "OpenSearch: период поиска с now-1M по now\n"
        "OpenSearch: период поиска с now-2M по now\n"
    )


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
