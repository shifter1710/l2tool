from types import SimpleNamespace

import gtool
import pytest
from core import parser
from gtool import format_event_time, format_opensearch_periods, format_phone_normalization


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
        match="Unknown module: bad. Available: zapis, bff, myconnect, myconnect_call",
    ):
        gtool.resolve_modules("bad")


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
