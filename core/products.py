PRODUCTS = {
    "recording": {
        "label": "Запись",
        "modules": ["zapis", "bff"],
    },
    "secretary": {
        "label": "Секретарь",
        "modules": ["bff"],
    },
    "calls": {
        "label": "Звонки",
        "modules": ["myconnect", "myconnect_call"],
    },
    "noise": {
        "label": "Шумоподавление",
        "modules": [],
    },
    "assistant": {
        "label": "Ассистент в звонке",
        "modules": [],
    },
}

PRODUCT_ORDER = ["recording", "secretary", "calls", "noise", "assistant"]


def resolve_product_label(product_key):
    try:
        return PRODUCTS[product_key]["label"]
    except KeyError as exc:
        available = ", ".join(sorted(PRODUCTS))
        raise ValueError(f"Unknown product key: {product_key}. Available products: {available}") from exc


def resolve_product_modules(product_key):
    try:
        product = PRODUCTS[product_key]
    except KeyError as exc:
        available = ", ".join(sorted(PRODUCTS))
        raise ValueError(f"Unknown product key: {product_key}. Available products: {available}") from exc

    return list(product["modules"])
