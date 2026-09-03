import json

import pytest

from core.products import available_products, product_title, resolve_product_modules


def test_recording_resolves_zapis_and_bff():
    assert resolve_product_modules("recording") == ["zapis", "sip_stack", "bff"]


def test_secretary_resolves_secretary_loki():
    assert resolve_product_modules("secretary") == ["secretary"]


def test_calls_resolves_myconnect_and_myconnect_call():
    assert resolve_product_modules("calls") == ["myconnect", "myconnect_call"]


def test_noise_resolves_noise_loki():
    assert resolve_product_modules("noise") == ["noise"]


def test_assistant_without_modules_returns_empty_list():
    assert resolve_product_modules("assistant") == []


def test_unknown_product_key_raises_clear_error():
    with pytest.raises(ValueError, match="Unknown product key: unknown"):
        resolve_product_modules("unknown")


def test_available_products_defaults_to_builtins_without_store(tmp_path):
    assert available_products(tmp_path / "missing.json") == [
        "recording",
        "secretary",
        "calls",
        "noise",
        "assistant",
    ]


def test_available_products_reads_store_catalog(tmp_path):
    store = tmp_path / "diagnostic_sources.json"
    store.write_text(
        json.dumps(
            {"version": 2, "products": [{"key": "recording"}, {"key": "custom"}], "sources": []}
        ),
        encoding="utf-8",
    )

    assert available_products(store) == ["recording", "custom"]


def test_product_title_prefers_store_title_over_builtin(tmp_path):
    store = tmp_path / "custom_store.json"
    store.write_text(
        json.dumps(
            {"version": 2, "products": [{"key": "recording", "title": "Запись МСК"}], "sources": []}
        ),
        encoding="utf-8",
    )

    assert product_title("recording", path=store) == "Запись МСК"
    assert product_title("recording") == "Запись"

    with pytest.raises(ValueError, match="Unknown product key"):
        product_title("custom", path=store)


def test_normalize_product_entries_fills_builtin_defaults(tmp_path):
    data = {
        "version": 2,
        "products": [
            {"key": "noise"},
            {"key": "zapis-msk", "title": "Запись МСК", "color": "teal"},
        ],
        "sources": [],
    }
    store = tmp_path / "diagnostic_sources.json"
    store.write_text(json.dumps(data), encoding="utf-8")

    from core.dynamic_sources import load_store

    entries = load_store(store)["products"]

    assert entries[0] == {
        "key": "noise",
        "title": "Шумоподавление",
        "color": "orange",
        "builtin": True,
        "managed": False,
    }
    assert entries[1]["managed"] is True
    assert entries[1]["builtin"] is False


def test_normalize_rejects_duplicate_and_invalid_products(tmp_path):
    from core.products import normalize_product_entries

    with pytest.raises(ValueError, match="латиница"):
        normalize_product_entries([{"key": "Не ключ"}])
    with pytest.raises(ValueError, match="Дублирующиеся ключи"):
        normalize_product_entries([{"key": "a"}, {"key": "a"}])
