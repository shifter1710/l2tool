PRODUCTS = {
    "recording": ("Запись", ["zapis", "sip_stack", "bff"]),
    "secretary": ("Секретарь", ["secretary"]),
    "calls": ("Звонки", ["myconnect", "myconnect_call"]),
    "noise": ("Шумоподавление", ["noise"]),
    "assistant": ("Ассистент в звонке", []),
}


def _unknown_product_error(product_key):
    available = ", ".join(sorted(PRODUCTS))
    return ValueError(f"Unknown product key: {product_key}. Available products: {available}")


def product_title(product_key):
    try:
        title, _modules = PRODUCTS[product_key]
    except KeyError as exc:
        raise _unknown_product_error(product_key) from exc

    return title


def resolve_product_modules(product_key):
    try:
        _title, modules = PRODUCTS[product_key]
    except KeyError as exc:
        raise _unknown_product_error(product_key) from exc

    return list(modules)


def available_products():
    return list(PRODUCTS)
