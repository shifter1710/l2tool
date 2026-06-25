import pytest

from core.products import resolve_product_modules


def test_recording_resolves_zapis_and_bff():
    assert resolve_product_modules("recording") == ["zapis", "bff"]


def test_secretary_resolves_bff():
    assert resolve_product_modules("secretary") == ["bff"]


def test_calls_resolves_myconnect_and_myconnect_call():
    assert resolve_product_modules("calls") == ["myconnect", "myconnect_call"]


@pytest.mark.parametrize("product_key", ["noise", "assistant"])
def test_products_without_modules_return_empty_list(product_key):
    assert resolve_product_modules(product_key) == []


def test_unknown_product_key_raises_clear_error():
    with pytest.raises(ValueError, match="Unknown product key: unknown"):
        resolve_product_modules("unknown")
