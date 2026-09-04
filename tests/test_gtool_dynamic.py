import json

import pytest

import gtool
from core.dynamic_sources import save_source
from gtool import resolve_modules

PHONE_URL = (
    "https://dashboards.example.local/app/data-explorer/discover"
    "#?_a=(metadata:(indexPattern:custom-view),"
    "query:(language:kuery,query:'msisdn:79991234567'))"
    "&_g=(time:(from:'2026-09-03T11:00:00.000',to:'2026-09-03T12:00:00.000'))"
)
UUID_URL = (
    "https://grafana.example.local/explore?panes=%7B%22A%22%3A%7B%22datasource%22"
    "%3A%22loki-custom%22%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22expr%22"
    "%3A%22%7Bjob%3D%5C%22calls%5C%22%7D%20%7C%3D%20%6012345678-1234-5678-1234-567812345678%60%22%7D%5D"
    "%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%2C%22to%22%3A%22now%22%7D%7D%7D&orgId=1"
)

TICKET = (
    "Номер клиента (msisdn): +7 (999) 123-45-67\n"
    "Дата и время проблемного звонка: 04.05.2026 10:30"
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


def write_ticket(tmp_path):
    ticket_path = tmp_path / "ticket.txt"
    ticket_path.write_text(TICKET, encoding="utf-8")
    return ticket_path


def run_cli(argv, monkeypatch, tmp_path):
    monkeypatch.setattr(gtool, "open_links", lambda links: None)
    monkeypatch.setattr("sys.argv", ["gtool.py", *argv])
    monkeypatch.chdir(tmp_path)
    return gtool.main()


def test_static_mode_without_store_resolves_static_modules():
    assert gtool.enabled_dynamic_sources() == []
    assert resolve_modules("zapis,bff") == ["zapis", "bff"]


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

    assert gtool.enabled_dynamic_sources() == []
    assert gtool.managed_product_keys() == set()
    assert gtool.product_open_arg("recording") == "zapis,sip_stack,bff"


def test_static_mode_dry_run_prints_static_links(monkeypatch, tmp_path, capsys):
    ticket_path = write_ticket(tmp_path)

    exit_code = run_cli(
        ["--file", str(ticket_path), "--open", "bff", "--dry-run"], monkeypatch, tmp_path
    )

    assert exit_code == 0
    assert "bff-example" in capsys.readouterr().out


def test_dynamic_mode_dry_run_prints_dynamic_links(monkeypatch, tmp_path, capsys):
    ticket_path = write_ticket(tmp_path)
    add_number_block()

    exit_code = run_cli(
        ["--file", str(ticket_path), "--product", "recording", "--dry-run"],
        monkeypatch,
        tmp_path,
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "[Пользовательский BFF]" in output
    assert "custom-view" in output


def test_dynamic_product_does_not_fall_back_to_static_modules(monkeypatch, tmp_path, capsys):
    ticket_path = write_ticket(tmp_path)
    add_number_block()

    exit_code = run_cli(
        ["--file", str(ticket_path), "--product", "recording", "--dry-run"],
        monkeypatch,
        tmp_path,
    )

    assert exit_code == 0
    assert "bff-example" not in capsys.readouterr().out


def test_open_accepts_block_id_and_name(monkeypatch, tmp_path, capsys):
    ticket_path = write_ticket(tmp_path)
    block = add_number_block()

    for open_arg in (block["id"], "Пользовательский BFF"):
        exit_code = run_cli(
            ["--file", str(ticket_path), "--open", open_arg, "--dry-run"],
            monkeypatch,
            tmp_path,
        )
        assert exit_code == 0
        assert "custom-view" in capsys.readouterr().out


def test_open_unknown_block_lists_available():
    block = add_number_block()

    with pytest.raises(ValueError) as error:
        resolve_modules("нет-такого-блока")

    message = str(error.value)
    assert "Unknown service: нет-такого-блока" in message
    assert f"Пользовательский BFF ({block['id']})" in message
    assert "zapis" in message


def test_menu_hides_products_without_blocks_and_static_services():
    add_number_block()

    assert gtool.menu_products() == ["recording", "secretary", "calls", "noise"]


def test_uuid_blocks_require_call_uuid(capsys):
    block = add_number_block(name="MGW блок")
    uuid_block = save_source(
        {
            "name": "UUID блок",
            "product": "recording",
            "level": "uuid",
            "example_url": UUID_URL,
            "sample_value": "",
            "minutes_before": 2,
            "minutes_after": 90,
        }
    )

    assert gtool.product_open_arg("recording") == block["id"]
    save_source(
        {
            "name": "Только UUID",
            "product": "noise",
            "level": "uuid",
            "example_url": UUID_URL,
            "sample_value": "",
            "minutes_before": 2,
            "minutes_after": 90,
        }
    )
    assert gtool.product_open_arg("noise") is None
    assert "передайте --call-uuid" in capsys.readouterr().out
    assert (
        gtool.product_open_arg(
            "recording", call_uuid="12345678-1234-5678-1234-567812345678"
        )
        == f"{block['id']},{uuid_block['id']}"
    )


def test_export_case_contains_dynamic_links(monkeypatch, tmp_path):
    ticket_path = write_ticket(tmp_path)
    block = add_number_block()
    export_path = tmp_path / "case.json"

    run_cli(
        ["--file", str(ticket_path), "--open", block["id"], "--export-case", str(export_path)],
        monkeypatch,
        tmp_path,
    )

    data = json.loads(export_path.read_text(encoding="utf-8"))
    assert data["search"]["selected_modules"] == [block["id"]]
    assert "custom-view" in data["search"]["links_by_module"][block["id"]][0]
    assert "Номер клиента" not in json.dumps(data)
    assert "ticket.txt" in data["source"]["file_name"]


def test_sidecar_contains_dynamic_links(monkeypatch, tmp_path):
    ticket_path = write_ticket(tmp_path)
    block = add_number_block()

    run_cli(
        ["--file", str(ticket_path), "--open", block["id"]], monkeypatch, tmp_path
    )

    sidecar = json.loads(
        ticket_path.with_name("ticket.parsed.json").read_text(encoding="utf-8")
    )
    assert "custom-view" in sidecar["search"]["links_by_module"][block["id"]][0]
