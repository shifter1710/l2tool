import re

# Встроенные продукты: значения по умолчанию, когда diagnostic_sources.json
# ещё нет. Ключи встроенных продуктов менять нельзя — на них ссылается CLI.
PRODUCTS = {
    "recording": ("Запись", ["zapis", "sip_stack", "bff"]),
    "secretary": ("Секретарь", ["secretary"]),
    "calls": ("Звонки", ["myconnect", "myconnect_call"]),
    "noise": ("Шумоподавление", ["noise"]),
    "assistant": ("Ассистент в звонке", []),
}

PRODUCT_COLORS = {
    "green": "#185c45",
    "violet": "#7652a6",
    "blue": "#2e7190",
    "orange": "#a05b32",
    "crimson": "#9c3550",
    "teal": "#2e8b74",
    "slate": "#50607a",
    "amber": "#a07d2c",
}
DEFAULT_PRODUCT_COLOR = "green"
MAX_PRODUCTS = 50
MAX_TITLE_LENGTH = 80
PRODUCT_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def builtin_product_keys():
    return list(PRODUCTS)


def is_builtin_product(product_key):
    return product_key in PRODUCTS


def builtin_product_title(product_key):
    return PRODUCTS[product_key][0]


def builtin_product_color(product_key):
    colors = {
        "recording": "green",
        "secretary": "violet",
        "calls": "blue",
        "noise": "orange",
        "assistant": "teal",
    }
    return colors.get(product_key, DEFAULT_PRODUCT_COLOR)


def default_product_entries():
    return [
        {
            "key": key,
            "title": builtin_product_title(key),
            "color": builtin_product_color(key),
            "builtin": True,
            "managed": False,
        }
        for key in PRODUCTS
    ]


def _unknown_product_error(product_key):
    available = ", ".join(sorted(PRODUCTS))
    return ValueError(f"Unknown product key: {product_key}. Available products: {available}")


def validate_product_key(product_key):
    key = str(product_key or "").strip()
    if not PRODUCT_KEY_PATTERN.fullmatch(key):
        raise ValueError(
            "Ключ продукта: 1–40 символов, латиница, цифры и дефис, "
            "начинается с буквы или цифры"
        )
    return key


def validate_product_title(title):
    value = str(title or "").strip()
    if not value or len(value) > MAX_TITLE_LENGTH:
        raise ValueError(
            f"Название продукта должно содержать от 1 до {MAX_TITLE_LENGTH} символов"
        )
    return value


def validate_product_color(color):
    value = str(color or "").strip()
    if not value:
        return None
    if value not in PRODUCT_COLORS:
        raise ValueError("Выберите цвет монограммы из списка")
    return value


def normalize_product_entry(raw, position):
    if not isinstance(raw, dict):
        raise ValueError(f"Продукт {position}: ожидается объект с настройками")
    key = validate_product_key(raw.get("key"))
    builtin = is_builtin_product(key)
    title = str(raw.get("title") or "").strip()
    if not title:
        title = builtin_product_title(key) if builtin else key
    if len(title) > MAX_TITLE_LENGTH:
        raise ValueError(f"Продукт {position}: название длиннее {MAX_TITLE_LENGTH} символов")
    color = raw.get("color")
    if color is not None and color not in PRODUCT_COLORS:
        raise ValueError(f"Продукт {position}: неизвестный цвет монограммы")
    if color is None and builtin:
        color = builtin_product_color(key)
    managed = bool(raw.get("managed")) if builtin else True
    return {"key": key, "title": title, "color": color, "builtin": builtin, "managed": managed}


def normalize_product_entries(raw_products):
    if not isinstance(raw_products, list):
        raise ValueError("Некорректный формат списка продуктов")
    entries = [
        normalize_product_entry(raw, index) for index, raw in enumerate(raw_products, start=1)
    ]
    keys = [entry["key"] for entry in entries]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise ValueError(f"Дублирующиеся ключи продуктов: {', '.join(duplicates)}")
    if len(entries) > MAX_PRODUCTS:
        raise ValueError(f"Продуктов не может быть больше {MAX_PRODUCTS}")
    return entries


def _store_entries(path=None):
    from core.dynamic_sources import load_store

    try:
        data = load_store(path)
    except (OSError, ValueError):
        return None
    return data.get("products", [])


def available_products(path=None):
    entries = _store_entries(path)
    if entries is None:
        return list(PRODUCTS)
    return [entry["key"] for entry in entries]


def product_title(product_key, path=None):
    entries = _store_entries(path)
    if entries is None:
        entries = default_product_entries()
    for entry in entries:
        if entry["key"] == product_key:
            return entry["title"]
    raise _unknown_product_error(product_key)


def resolve_product_modules(product_key):
    try:
        _title, modules = PRODUCTS[product_key]
    except KeyError as exc:
        raise _unknown_product_error(product_key) from exc

    return list(modules)
