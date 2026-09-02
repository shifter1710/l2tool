import pytest

from core.products import resolve_product_modules


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
