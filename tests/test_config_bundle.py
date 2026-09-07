import json

import httpx

import webapp
from core import config, config_bundle, dynamic_sources, reference_codes, runbook
from tests.test_call_history import HISTORY_SAMPLE  # noqa: F401  (общая фикстура)


def opensearch_link():
    return (
        "https://dashboards.example.local/app/data-explorer/discover"
        "#?_a=(metadata:(indexPattern:bundle-example,view:discover),"
        "query:(language:kuery,query:'msisdn:79991234567'))"
        "&_g=(time:(from:'2026-09-08T11:00:00.000',to:'2026-09-08T12:00:00.000'))"
    )


def filled_stores():
    dynamic_sources.save_source(
        {
            "name": "Бандл-блок",
            "product": "recording",
            "level": "number",
            "example_url": opensearch_link(),
            "sample_value": "",
        }
    )
    dynamic_sources.save_call_history_secretary_numbers("79991230777")
    reference_codes.import_store(json.dumps({"Decision": {"10": "Вне покрытия"}}))
    case = {
        "id": "case", "symptom": "Симптом",
        "steps": [{"source": None, "note": "Проверить логи"}],
    }
    runbook.import_store(json.dumps([case]))


def test_build_bundle_contains_all_stores():
    filled_stores()

    bundle = config_bundle.build_bundle()

    assert bundle["l2tool"] == "configs"
    assert bundle["version"] == 1
    assert bundle["stores"]["diagnostic_sources"]["sources"]
    assert bundle["stores"]["reference_codes"] == {"Decision": {"10": "Вне покрытия"}}
    assert bundle["stores"]["runbook"][0]["id"] == "case"
    # config.toml из фикстуры conftest входит в бандл
    assert "services.zapis" in bundle["config_toml"]


def test_import_bundle_roundtrip_into_fresh_store(tmp_path, monkeypatch):
    filled_stores()
    bundle = config_bundle.build_bundle()

    # «Другая машина»: пустые хранилища в отдельном подкаталоге
    # (conftest уже занял tmp_path для изоляции текущего состояния)
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    monkeypatch.setattr(dynamic_sources, "STORE_PATH", fresh / "diagnostic_sources.json")
    monkeypatch.setattr(reference_codes, "STORE_PATH", fresh / "reference_codes.json")
    monkeypatch.setattr(runbook, "STORE_PATH", fresh / "runbook.json")
    monkeypatch.setattr(config_bundle, "CONFIG_PATH", fresh / "config.toml")
    monkeypatch.setattr(config, "CONFIG_PATH", fresh / "config.toml")

    report = config_bundle.import_bundle(json.dumps(bundle, ensure_ascii=False))

    assert report["errors"] == []
    assert "добавлено 1" in report["stores"]["diagnostic_sources"]
    assert report["stores"]["reference_codes"].startswith("справочник заменён: 1")
    assert report["stores"]["runbook"].startswith("ранбук заменён: 1")
    assert report["stores"]["config_toml"].startswith("config.toml заменён")
    assert (fresh / "config.toml").exists()
    assert load_secretary_numbers() == ["79991230777"]

    # Повторный импорт того же бандла: блоки дублируются — пропускаются
    report_again = config_bundle.import_bundle(json.dumps(bundle, ensure_ascii=False))
    assert "добавлено 0, пропущено 1" in report_again["stores"]["diagnostic_sources"]


def load_secretary_numbers():
    from core import call_history

    return call_history.secretary_numbers_ordered()


def test_import_bundle_creates_missing_custom_product(tmp_path, monkeypatch):
    bundle = {
        "l2tool": "configs",
        "version": 1,
        "stores": {
            "diagnostic_sources": {
                "version": 2,
                "products": [
                    {"key": "custom-team", "title": "Команда", "color": "teal"},
                ],
                "sources": [
                    {
                        "name": "Чужой блок",
                        "product": "custom-team",
                        "level": "number",
                        "example_url": opensearch_link(),
                        "sample_value": "",
                        "minutes_before": 2,
                        "minutes_after": 90,
                    }
                ],
            }
        },
    }

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    monkeypatch.setattr(dynamic_sources, "STORE_PATH", fresh / "diagnostic_sources.json")
    report = config_bundle.import_bundle(json.dumps(bundle, ensure_ascii=False))

    assert report["errors"] == []
    assert "custom-team" in dynamic_sources.available_products()
    sources = dynamic_sources.load_store()["sources"]
    assert any(source["product"] == "custom-team" for source in sources)


def test_import_bundle_rejects_bad_input():
    try:
        config_bundle.import_bundle("{}")
    except ValueError as error:
        assert "не бандл" in str(error)
    else:
        raise AssertionError("expected ValueError")

    try:
        config_bundle.import_bundle(json.dumps({"l2tool": "configs", "version": 99, "stores": {}}))
    except ValueError as error:
        assert "версия" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_import_config_toml_validates_and_backs_up(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text('key = "old"\n', encoding="utf-8")
    monkeypatch.setattr(config_bundle, "CONFIG_PATH", config_path)

    config_bundle.import_config_toml('[defaults]\nwindow = 45\n')
    assert config_path.read_text(encoding="utf-8") == '[defaults]\nwindow = 45\n'
    backups = list((tmp_path / "backups").glob("config.toml.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == 'key = "old"\n'

    for bad in ("это не toml {{{", 'url = "https://x/?access_token=1"'):
        try:
            config_bundle.import_config_toml(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad!r}")


def test_import_config_toml_rejects_secrets_and_dangerous_schemes(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[defaults]\nwindow = 60\n', encoding="utf-8")
    monkeypatch.setattr(config_bundle, "CONFIG_PATH", config_path)

    for bad in (
        '[services.zapis]\ntoken = "abc"\n',  # TOML-стиль с пробелами вокруг «=»
        '[services.zapis]\npassword = "hunter2"\n',
        '[services.zapis]\nurl = "javascript:alert(1)"\n',
        '[services.zapis]\nurl = "https://user:pass@grafana.example.local/d/x"\n',
    ):
        try:
            config_bundle.import_config_toml(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad!r}")
    # Отказ не трогает существующий файл
    assert config_path.read_text(encoding="utf-8") == '[defaults]\nwindow = 60\n'


def test_build_bundle_skips_config_toml_with_secrets(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[services.zapis]\n'
        'url = "https://grafana.example.local/d/x?orgId=1&token=secret"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_bundle, "CONFIG_PATH", config_path)

    bundle = config_bundle.build_bundle()

    assert "config_toml" not in bundle
    assert "token" in bundle["skipped"]["config_toml"]
    assert "пропущен" in config_bundle.bundle_summary()


def test_web_export_all_returns_bundle():
    response = request("GET", "/settings/export-all")

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="l2tool-configs-'
    )
    bundle = json.loads(response.text)
    assert bundle["l2tool"] == "configs"
    assert "diagnostic_sources" in bundle["stores"]


def test_web_import_all_applies_bundle():
    filled_stores()
    bundle = config_bundle.build_bundle()
    files = {"bundle_file": ("l2tool-configs.json", json.dumps(bundle), "application/json")}
    response = request(
        "POST",
        "/settings/import-all",
        data={"csrf_token": webapp.app.state.csrf_token},
        files=files,
    )

    assert response.status_code == 200
    assert "Отчёт о загрузке бандла" in response.text
    assert "справочник заменён: 1" in response.text

    wrong = request(
        "POST",
        "/settings/import-all",
        data={"csrf_token": webapp.app.state.csrf_token},
        files={"bundle_file": ("x.json", b"{}", "application/json")},
    )
    assert wrong.status_code == 400
    assert "не бандл" in wrong.text


def test_web_import_config_route(tmp_path, monkeypatch):
    monkeypatch.setattr(config_bundle, "CONFIG_PATH", tmp_path / "config.toml")
    response = request(
        "POST",
        "/settings/import-config",
        data={"csrf_token": webapp.app.state.csrf_token},
        files={
            "config_toml_file": ("config.toml", b'[defaults]\nwindow = 45\n', "application/toml")
        },
    )

    assert response.status_code == 303
    assert (tmp_path / "config.toml").read_text(encoding="utf-8") == '[defaults]\nwindow = 45\n'


def test_web_export_config_route(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "CONFIG_PATH", tmp_path / "missing.toml")
    assert request("GET", "/settings/export-config").status_code == 404

    config_path = tmp_path / "config.toml"
    config_path.write_text("[defaults]\nwindow = 45\n", encoding="utf-8")
    monkeypatch.setattr(webapp, "CONFIG_PATH", config_path)
    response = request("GET", "/settings/export-config")

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="config.toml"'
    )
    assert "window = 45" in response.text


def test_defaults_come_from_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                '[defaults]',
                'window = 45',
                'product = "recording"',
                'calls_product = "calls"',
                '[gtool]',
                'default_open = "zapis"',
                '[call_history]',
                'default_open = "zapis"',
                "max_calls = 7",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)

    import gtool

    assert gtool.configured_default_window() == 45
    assert gtool.configured_default_open() == "zapis"
    assert gtool.configured_call_history_open() == "zapis"
    assert gtool.configured_call_history_max_calls() == 7
    assert gtool.configured_default_product() == "recording"
    assert gtool.configured_calls_product() == "calls"

    home = request("GET", "/")
    assert 'value="45"' in home.text


def request(method, path, **kwargs):
    import asyncio

    def send():
        transport = httpx.ASGITransport(app=webapp.app)

        async def run():
            async with httpx.AsyncClient(
                transport=transport, base_url="http://localhost"
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(run())

    return send()
