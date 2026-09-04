import json
import os
import re
import secrets
import threading
from datetime import datetime, time, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from core.products import (
    available_products,
    builtin_product_title,
    default_product_entries,
    is_builtin_product,
    normalize_product_entries,
    product_title,
    validate_product_color,
    validate_product_key,
    validate_product_title,
)
from core.source_backups import create_backup
from core.time_windows import utc_search_windows
from core.utils import hash_phone, normalize_uuid
from services.opensearch import extract_index_pattern

ROOT_DIR = Path(__file__).resolve().parents[1]
STORE_PATH = ROOT_DIR / "diagnostic_sources.json"
STORE_VERSION = 2
LEVELS = {"number": "Поиск по номерам", "uuid": "Поиск по UUID"}
MAX_URL_LENGTH = 100_000
MAX_IMPORTED_SOURCES = 500
_WRITE_LOCK = threading.RLock()
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:[78]\d{10}|\d{10})(?!\d)")
_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_SENSITIVE_PATTERN = re.compile(
    r"(?:[?&#]|^)(?:access_token|api_key|apikey|auth|token)=",
    re.IGNORECASE,
)


def _empty_store():
    return {"version": STORE_VERSION, "products": default_product_entries(), "sources": []}


def _migrated_products(managed_products):
    """Каталог продуктов схемы v2 из массива строк managed_products (схема v1)."""
    managed = managed_products if isinstance(managed_products, list) else []
    entries = [
        {"key": key["key"], "builtin": True, "managed": key["key"] in managed}
        for key in default_product_entries()
    ]
    known = {entry["key"] for entry in entries}
    entries.extend({"key": key} for key in managed if isinstance(key, str) and key not in known)
    return entries


def load_store(path=None):
    path = Path(path or STORE_PATH)
    if not path.exists():
        return _empty_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Не удалось прочитать настройки диагностических блоков") from error
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise ValueError("Некорректный формат настроек диагностических блоков")
    version = data.get("version", 1)
    if version not in {1, STORE_VERSION}:
        raise ValueError(f"Неподдерживаемая версия настроек: {version}")
    raw_products = data.get("products")
    if raw_products is None:
        raw_products = _migrated_products(data.get("managed_products"))
    data["products"] = normalize_product_entries(raw_products)
    data["version"] = STORE_VERSION
    data.pop("managed_products", None)
    return data


def write_store(data, path=None):
    path = Path(path or STORE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    with _WRITE_LOCK:
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                json.dump(data, temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.chmod(temporary_path, 0o600)
            load_store(temporary_path)
            temporary_path.replace(path)
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()


def _normalize_phone(value):
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 10:
        return "7" + digits
    if len(digits) == 11 and digits.startswith("8"):
        return "7" + digits[1:]
    if len(digits) == 11 and digits.startswith("7"):
        return digits
    raise ValueError("Значение-пример должно содержать корректный номер телефона")


def _parse_platform(url):
    value = url.strip()
    if not value or len(value) > MAX_URL_LENGTH:
        raise ValueError("Вставьте корректную полную ссылку")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Ссылка должна начинаться с http:// или https://")
    if parts.username or parts.password:
        raise ValueError("Удалите логин и пароль из ссылки")
    if _SENSITIVE_PATTERN.search(value):
        raise ValueError("Удалите токен или ключ доступа из ссылки")

    index_pattern = extract_index_pattern(value)
    if index_pattern:
        return {
            "platform": "opensearch",
            "kind": "discover",
            "host": parts.hostname,
            "index_pattern": index_pattern,
        }

    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if "/explore" in parts.path or "panes" in query or "left" in query:
        state_found = False
        for key in ("panes", "left"):
            if key not in query:
                continue
            try:
                json.loads(query[key])
            except json.JSONDecodeError as error:
                raise ValueError(f"Не удалось разобрать параметр Grafana {key}") from error
            state_found = True
        if not state_found:
            raise ValueError("Ссылка Grafana Explore должна содержать panes или left")
        return {"platform": "grafana", "kind": "explore", "host": parts.hostname}

    if re.search(r"/(?:d|d-solo)/[^/]+", parts.path):
        return {"platform": "grafana", "kind": "dashboard", "host": parts.hostname}
    raise ValueError("Не удалось распознать Grafana или OpenSearch Discover")


def _strategy_candidates(level, sample_value):
    if level == "number":
        normalized = _normalize_phone(sample_value)
        return (
            ("raw", normalized),
            ("national", normalized[1:]),
            ("hash16", hash_phone(normalized)),
        )
    normalized = normalize_uuid(sample_value)
    return (("raw", normalized), ("compact_uuid", normalized.replace("-", "")))


def _detect_one_sample(level, decoded, sample_value):
    candidates = _strategy_candidates(level, sample_value)
    decoded_lower = decoded.lower()
    for strategy, candidate in candidates:
        if candidate.lower() in decoded_lower:
            return {"strategy": strategy, "match_value": candidate}
    raise ValueError(
        "Значение-пример не найдено в ссылке ни в исходном, ни в преобразованном виде"
    )


def _detect_samples(level, url, sample_value):
    decoded = _fully_unquote(url)
    if sample_value:
        sample_values = [
            value for value in re.split(r"[,;\s]+", sample_value) if value
        ]
    elif level == "number":
        sample_values = list(dict.fromkeys(_PHONE_PATTERN.findall(decoded)))[:2]
        if not sample_values:
            raise ValueError(
                "Не удалось найти номер в ссылке. Укажите значение-пример вручную"
            )
    else:
        match = _UUID_PATTERN.search(decoded)
        if not match:
            raise ValueError(
                "Не удалось найти UUID в ссылке. Укажите значение-пример вручную"
            )
        sample_values = [match.group(0)]

    if level == "uuid" and len(sample_values) != 1:
        raise ValueError("Для UUID-блока укажите одно значение-пример")
    if level == "number" and len(sample_values) > 2:
        raise ValueError("Для блока по номерам можно указать не более двух примеров")
    return [
        _detect_one_sample(level, decoded, value) for value in sample_values
    ]


def _source_slots(source):
    slots = source.get("replacements")
    if isinstance(slots, list) and slots:
        return slots
    try:
        return _detect_samples(
            source["level"],
            source["example_url"],
            source.get("sample_value", ""),
        )
    except (KeyError, TypeError, ValueError):
        return [
            {
                "strategy": source["strategy"],
                "match_value": source["match_value"],
            }
        ]


def _fully_unquote(value):
    previous = value
    for _ in range(3):
        current = unquote(previous)
        if current == previous:
            break
        previous = current
    return previous


def validate_source(values, path=None):
    name = str(values.get("name", "")).strip()
    product = str(values.get("product", "")).strip()
    level = str(values.get("level", "")).strip()
    url = str(values.get("example_url", "")).strip()
    sample_value = str(values.get("sample_value", "")).strip()
    if not name or len(name) > 80:
        raise ValueError("Название блока должно содержать от 1 до 80 символов")
    if product not in available_products(path):
        raise ValueError("Выберите существующий продукт")
    if level not in LEVELS:
        raise ValueError("Выберите уровень поиска")

    parsed = _parse_platform(url)
    replacements = _detect_samples(level, url, sample_value)
    try:
        minutes_before = int(values.get("minutes_before", 2))
        minutes_after = int(values.get("minutes_after", 90))
    except (TypeError, ValueError) as error:
        raise ValueError("Окно поиска должно быть задано целым числом минут") from error
    if not 0 <= minutes_before <= 1440 or not 0 <= minutes_after <= 1440:
        raise ValueError("Окно поиска должно быть от 0 до 1440 минут")

    return {
        "name": name,
        "product": product,
        "level": level,
        "example_url": url,
        "sample_value": sample_value,
        "platform": parsed["platform"],
        "kind": parsed["kind"],
        "host": parsed["host"],
        "index_pattern": parsed.get("index_pattern"),
        "strategy": replacements[0]["strategy"],
        "match_value": replacements[0]["match_value"],
        "replacements": replacements,
        "minutes_before": minutes_before,
        "minutes_after": minutes_after,
    }


def _ensure_product(data, product):
    """Продукт существует в каталоге; встроенный переводится в управляемый."""
    for entry in data["products"]:
        if entry["key"] == product:
            if entry["builtin"] and not entry["managed"]:
                entry["managed"] = True
            return
    if is_builtin_product(product):
        data["products"].append(
            {
                "key": product,
                "title": builtin_product_title(product),
                "color": None,
                "builtin": True,
                "managed": True,
            }
        )
        return
    raise ValueError("Выберите существующий продукт")


def save_source(values, source_id=None, path=None):
    source = validate_source(values, path)
    with _WRITE_LOCK:
        data = load_store(path)
        existing_index = None
        if source_id:
            existing_index = next(
                (
                    index
                    for index, item in enumerate(data["sources"])
                    if item.get("id") == source_id
                ),
                None,
            )
            if existing_index is None:
                raise ValueError("Диагностический блок не найден")
            source["id"] = source_id
            source["enabled"] = data["sources"][existing_index].get("enabled", True)
        else:
            source["id"] = secrets.token_hex(8)
            source["enabled"] = True

        _ensure_product(data, source["product"])
        if existing_index is None:
            data["sources"].append(source)
        else:
            data["sources"][existing_index] = source
        create_backup(path)
        write_store(data, path)
    return source


def delete_source(source_id, path=None):
    with _WRITE_LOCK:
        data = load_store(path)
        remaining = [item for item in data["sources"] if item.get("id") != source_id]
        if len(remaining) == len(data["sources"]):
            raise ValueError("Диагностический блок не найден")
        data["sources"] = remaining
        create_backup(path)
        write_store(data, path)


def set_source_enabled(source_id, enabled, path=None):
    with _WRITE_LOCK:
        data = load_store(path)
        source = _find_source(data, source_id)
        source["enabled"] = bool(enabled)
        create_backup(path)
        write_store(data, path)
    return source


def duplicate_source(source_id, path=None):
    with _WRITE_LOCK:
        data = load_store(path)
        index = _source_index(data, source_id)
        original = data["sources"][index]
        copy = dict(original)
        copy["id"] = secrets.token_hex(8)
        copy["name"] = _copy_name(original["name"])
        data["sources"].insert(index + 1, copy)
        create_backup(path)
        write_store(data, path)
    return copy


def _copy_name(name):
    suffix = " (копия)"
    if len(name) + len(suffix) <= 80:
        return name + suffix
    return name[: 80 - len(suffix)].rstrip() + suffix


def move_source(source_id, direction, path=None):
    """Сдвинуть блок выше/ниже внутри своего продукта и уровня."""
    if direction not in {"up", "down"}:
        raise ValueError("Неизвестное направление перемещения")
    with _WRITE_LOCK:
        data = load_store(path)
        index = _source_index(data, source_id)
        source = data["sources"][index]
        order = [
            position
            for position, item in enumerate(data["sources"])
            if item.get("product") == source.get("product")
            and item.get("level") == source.get("level")
        ]
        position = order.index(index)
        neighbor_position = position - 1 if direction == "up" else position + 1
        if not 0 <= neighbor_position < len(order):
            return False
        neighbor_index = order[neighbor_position]
        data["sources"][index], data["sources"][neighbor_index] = (
            data["sources"][neighbor_index],
            data["sources"][index],
        )
        create_backup(path)
        write_store(data, path)
    return True


def set_product_sources_enabled(product, enabled, path=None):
    with _WRITE_LOCK:
        data = load_store(path)
        changed = 0
        for source in data["sources"]:
            if source.get("product") == product and source.get("enabled", True) != bool(enabled):
                source["enabled"] = bool(enabled)
                changed += 1
        if not changed:
            return 0
        create_backup(path)
        write_store(data, path)
    return changed


def _find_source(data, source_id):
    index = _source_index(data, source_id)
    return data["sources"][index]


def _source_index(data, source_id):
    for index, item in enumerate(data["sources"]):
        if item.get("id") == source_id:
            return index
    raise ValueError("Диагностический блок не найден")


def list_products(path=None):
    data = load_store(path)
    counts = {}
    for source in data["sources"]:
        product = source.get("product")
        counts[product] = counts.get(product, 0) + 1
    entries = []
    for entry in data["products"]:
        item = dict(entry)
        item["source_count"] = counts.get(entry["key"], 0)
        entries.append(item)
    return entries


def create_product(key, title, color=None, path=None):
    key = validate_product_key(key)
    title = validate_product_title(title)
    color = validate_product_color(color)
    with _WRITE_LOCK:
        data = load_store(path)
        if any(entry["key"] == key for entry in data["products"]):
            raise ValueError("Продукт с таким ключом уже существует")
        if len(data["products"]) >= 50:
            raise ValueError("Достигнут лимит количества продуктов")
        if is_builtin_product(key):
            entry = {"key": key, "title": title, "color": color, "builtin": True, "managed": False}
        else:
            entry = {"key": key, "title": title, "color": color, "managed": True}
        data["products"].append(entry)
        create_backup(path)
        write_store(data, path)
    return entry


def update_product(key, title, color=None, new_key=None, path=None):
    title = validate_product_title(title)
    color = validate_product_color(color)
    with _WRITE_LOCK:
        data = load_store(path)
        entry = next(
            (item for item in data["products"] if item["key"] == key), None
        )
        if entry is None:
            raise ValueError("Продукт не найден")
        final_key = key
        if new_key and str(new_key).strip() != key:
            if entry["builtin"]:
                raise ValueError("Ключ встроенного продукта изменить нельзя")
            final_key = validate_product_key(new_key)
            if any(item["key"] == final_key for item in data["products"]):
                raise ValueError("Продукт с таким ключом уже существует")
        entry["title"] = title
        entry["color"] = color
        if final_key != key:
            entry["key"] = final_key
            for source in data["sources"]:
                if source.get("product") == key:
                    source["product"] = final_key
        create_backup(path)
        write_store(data, path)
    return entry


def delete_product(key, path=None):
    with _WRITE_LOCK:
        data = load_store(path)
        if not any(entry["key"] == key for entry in data["products"]):
            raise ValueError("Продукт не найден")
        blocks = [item for item in data["sources"] if item.get("product") == key]
        if blocks:
            raise ValueError(
                f"У продукта «{product_title(key, path=path)}» есть блоки "
                f"({len(blocks)} шт.). Сначала удалите их или перенесите в другой продукт."
            )
        data["products"] = [entry for entry in data["products"] if entry["key"] != key]
        create_backup(path)
        write_store(data, path)


def import_sources(content, path=None):
    try:
        imported = json.loads(content)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Файл должен содержать корректный JSON") from error

    raw_sources = imported.get("sources") if isinstance(imported, dict) else imported
    if not isinstance(raw_sources, list):
        raise ValueError("В конфигурации должен быть массив sources")
    if not raw_sources:
        raise ValueError("В конфигурации нет диагностических блоков")
    if len(raw_sources) > MAX_IMPORTED_SOURCES:
        raise ValueError(f"За один раз можно импортировать не более {MAX_IMPORTED_SOURCES} блоков")

    validated = []
    for index, raw_source in enumerate(raw_sources, start=1):
        if not isinstance(raw_source, dict):
            raise ValueError(f"Блок {index}: ожидается объект с настройками")
        try:
            validated.append(validate_source(raw_source, path))
        except ValueError as error:
            raise ValueError(f"Блок {index}: {error}") from error

    with _WRITE_LOCK:
        data = load_store(path)
        signatures = {
            (
                source.get("name"),
                source.get("product"),
                source.get("level"),
                source.get("example_url"),
            )
            for source in data["sources"]
        }
        added = 0
        skipped = 0
        for source in validated:
            signature = (
                source["name"],
                source["product"],
                source["level"],
                source["example_url"],
            )
            if signature in signatures:
                skipped += 1
                continue
            source["id"] = secrets.token_hex(8)
            source["enabled"] = True
            data["sources"].append(source)
            signatures.add(signature)
            _ensure_product(data, source["product"])
            added += 1
        if added:
            create_backup(path)
            write_store(data, path)
    return {"added": added, "skipped": skipped}


def import_services_from_config(product, path=None, config_path=None, sample_value=""):
    """Односторонний мост: сервисы из config.toml → динамические блоки.

    sample_value — необязательный номер из существующих ссылок: помогает
    распознать подстановку, когда в URL стоит хеш номера (например, BFF).
    """
    from core.config import load_config

    if product not in available_products(path):
        raise ValueError("Выберите существующий продукт")
    config = load_config(config_path)
    services = config.get("services")
    if not isinstance(services, dict):
        raise ValueError("В config.toml нет секций [services.*]")

    from services.registry import SERVICES

    report = {"added": 0, "skipped": 0, "errors": []}
    candidates = []
    seen_urls = {
        (source.get("product"), source.get("level"), source.get("example_url"))
        for source in load_store(path)["sources"]
    }
    with_url = 0
    for name, options in services.items():
        if not isinstance(options, dict):
            continue
        url = str(options.get("url") or "").strip()
        if not url:
            continue
        with_url += 1
        signature = (product, "number", url)
        if signature in seen_urls:
            report["skipped"] += 1
            continue
        title = SERVICES[name].title if name in SERVICES else str(name)
        values = {
            "name": title,
            "product": product,
            "level": "number",
            "example_url": url,
            "sample_value": "",
            "minutes_before": options.get("minutes_before", 2),
            "minutes_after": options.get("minutes_after", 90),
        }
        try:
            candidates.append(validate_source(values, path))
        except ValueError as error:
            if sample_value and "значение-пример" in str(error):
                values["sample_value"] = sample_value
                try:
                    candidates.append(validate_source(values, path))
                    continue
                except ValueError:
                    pass
            report["errors"].append(f"{title}: {error}")

    if not with_url:
        raise ValueError("В config.toml не найдено сервисов с заполненным url")

    with _WRITE_LOCK:
        data = load_store(path)
        for source in candidates:
            signature = (source["product"], source["level"], source["example_url"])
            if signature in seen_urls:
                report["skipped"] += 1
                continue
            source["id"] = secrets.token_hex(8)
            source["enabled"] = True
            data["sources"].append(source)
            seen_urls.add(signature)
            report["added"] += 1
        if report["added"]:
            _ensure_product(data, product)
            create_backup(path)
            write_store(data, path)
    return report


def list_sources(product=None, level=None, path=None, enabled_only=False):
    sources = load_store(path)["sources"]
    return [
        source
        for source in sources
        if (product is None or source.get("product") == product)
        and (level is None or source.get("level") == level)
        and (not enabled_only or source.get("enabled", True))
    ]


def is_managed(product, path=None):
    entry = next(
        (item for item in load_store(path)["products"] if item["key"] == product), None
    )
    if entry is None:
        return False
    return entry["managed"] or not entry["builtin"]


def product_groups(overrides=None, path=None):
    data = load_store(path)
    overrides = overrides or {}
    sources = []
    for source in data["sources"]:
        item = dict(source)
        item["replacements"] = _source_slots(item)
        if item["id"] in overrides:
            item.update(overrides[item["id"]])
        sources.append(item)
    groups = []
    for entry in data["products"]:
        key = entry["key"]
        groups.append(
            {
                "key": key,
                "title": entry["title"],
                "color": entry.get("color"),
                "builtin": entry["builtin"],
                "managed": entry["managed"] or not entry["builtin"],
                "levels": [
                    {
                        "key": level,
                        "title": title,
                        "sources": [
                            source
                            for source in sources
                            if source["product"] == key and source["level"] == level
                        ],
                    }
                    for level, title in LEVELS.items()
                ],
            }
        )
    return groups


def preview_source(values, preview_value, path=None):
    """Итоговые ссылки по черновику блока и тестовому значению, без записи."""
    try:
        source = validate_source(values, path)
    except (KeyError, TypeError, ValueError) as error:
        return {"error": str(error), "links": []}
    try:
        ctx = _preview_context(source["level"], preview_value)
        links = build_source_links(source, ctx, call_uuid=ctx.get("call_uuid"))
    except (KeyError, TypeError, ValueError) as error:
        return {"error": str(error), "links": []}
    if not links:
        return {"error": "Не удалось построить ссылку по указанным настройкам", "links": []}
    return {"error": None, "links": links}


def _preview_context(level, preview_value):
    test_value = str(preview_value or "").strip()
    if not test_value:
        raise ValueError("Укажите тестовый номер или UUID")
    now = datetime.now()
    ctx = {"event_time": now, "event_datetimes": [now], "tz": "Europe/Moscow", "window": 60}
    if level == "uuid":
        ctx["call_uuid"] = normalize_uuid(test_value)
        return ctx
    phone = _normalize_phone(test_value)
    ctx.update(
        {
            "msisdn": phone,
            "msisdn_values": [phone],
            "phone_a": phone,
            "phone_a_values": [phone],
            "phone_b": phone,
            "phone_b_values": [phone],
        }
    )
    return ctx


def _replacement_for(level, strategy, value):
    if level == "number":
        normalized = _normalize_phone(value)
        if strategy == "national":
            return normalized[1:]
        if strategy == "hash16":
            return hash_phone(normalized)
        return normalized
    normalized = normalize_uuid(value)
    return normalized.replace("-", "") if strategy == "compact_uuid" else normalized


def _replace_text(value, old, new):
    return re.sub(re.escape(old), lambda _match: new, value, flags=re.IGNORECASE)


def _replace_pairs(value, replacements):
    placeholders = []
    updated = value
    for index, (old, new) in enumerate(replacements):
        placeholder = f"__L2TOOL_PHONE_SLOT_{index}__"
        updated = _replace_text(updated, old, placeholder)
        placeholders.append((placeholder, new))
    for placeholder, new in placeholders:
        updated = updated.replace(placeholder, new)
    return updated


def _replace_tree(node, replacements, time_range=None):
    if isinstance(node, str):
        return _replace_pairs(node, replacements)
    if isinstance(node, list):
        return [_replace_tree(item, replacements, time_range) for item in node]
    if isinstance(node, dict):
        updated = {
            key: _replace_tree(value, replacements, time_range)
            for key, value in node.items()
        }
        if time_range and isinstance(updated.get("range"), dict):
            updated["range"] = {**updated["range"], "from": time_range[0], "to": time_range[1]}
        return updated
    return node


def _grafana_links(source, replacements, ctx):
    parts = urlsplit(source["example_url"])
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    windows = utc_search_windows(ctx) or [None]
    links = []
    for window in windows:
        updated = {}
        for key, value in params.items():
            if key in {"panes", "left"}:
                state = json.loads(value)
                updated[key] = json.dumps(
                    _replace_tree(state, replacements, window),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            else:
                updated[key] = _replace_pairs(value, replacements)
        if window and source["kind"] == "dashboard":
            updated["from"], updated["to"] = window
        links.append(
            urlunsplit(
                (parts.scheme, parts.netloc, parts.path, urlencode(updated), parts.fragment)
            )
        )
    return links


def _opensearch_period(source, ctx):
    values = list(ctx.get("event_datetimes") or [])
    if not values and ctx.get("event_time"):
        values = [ctx["event_time"]]
    if ctx.get("event_time_range"):
        start, end = ctx["event_time_range"]
    elif values:
        start, end = min(values), max(values)
    elif ctx.get("event_date"):
        start = datetime.combine(ctx["event_date"], time(hour=8))
        end = datetime.combine(ctx["event_date"], time(hour=20))
    else:
        return None
    source_tz = ZoneInfo(ctx.get("tz", "Europe/Moscow"))
    target_tz = ZoneInfo("Europe/Moscow")

    def to_target(value):
        if value.tzinfo is None:
            value = value.replace(tzinfo=source_tz)
        return value.astimezone(target_tz).replace(tzinfo=None)

    start = to_target(start) - timedelta(minutes=source["minutes_before"])
    end = to_target(end) + timedelta(minutes=source["minutes_after"])
    return start.strftime("%Y-%m-%dT%H:%M:%S.000"), end.strftime("%Y-%m-%dT%H:%M:%S.000")


def _opensearch_link(source, replacements, ctx):
    parts = urlsplit(source["example_url"])
    fragment = _fully_unquote(parts.fragment)
    fragment = _replace_pairs(fragment, replacements)
    period = _opensearch_period(source, ctx)
    if period:
        time_pattern = re.compile(
            r"time:\(from:(?:'[^']*'|[^,)]*),to:(?:'[^']*'|[^)]*)\)"
        )
        fragment, replaced = time_pattern.subn(
            f"time:(from:'{period[0]}',to:'{period[1]}')",
            fragment,
            count=1,
        )
        if not replaced:
            raise ValueError(
                "Ссылка не содержит временной диапазон — скопируйте ссылку "
                "с выбранным периодом времени"
            )
    encoded_fragment = quote(fragment, safe="!$&'()*+,-./:;=?@_~")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, encoded_fragment))


def _first_phone(ctx, field):
    values = ctx.get(f"{field}_values") or [ctx.get(field)]
    return next((value for value in values if value), None)


def _resolved_phone_pair(ctx):
    client = _first_phone(ctx, "msisdn")
    phone_a = _first_phone(ctx, "phone_a")
    phone_b = _first_phone(ctx, "phone_b")

    if not phone_a and not phone_b:
        if not client:
            raise ValueError("В заявке не найден номер клиента или номера А/Б")
        return client, client
    if not phone_a:
        phone_a = client or phone_b
    if not phone_b:
        phone_b = client or phone_a
    return phone_a, phone_b


def build_source_links(source, ctx, call_uuid=None):
    slots = _source_slots(source)
    if source["level"] == "uuid":
        if not call_uuid:
            raise ValueError("UUID звонка не указан")
        replacement_sets = [
            [
                (
                    slots[0]["match_value"],
                    _replacement_for("uuid", slots[0]["strategy"], call_uuid),
                )
            ]
        ]
    elif len(slots) >= 2:
        phone_a, phone_b = _resolved_phone_pair(ctx)
        replacement_sets = [
            [
                (
                    slots[0]["match_value"],
                    _replacement_for("number", slots[0]["strategy"], phone_a),
                ),
                (
                    slots[1]["match_value"],
                    _replacement_for("number", slots[1]["strategy"], phone_b),
                ),
            ]
        ]
    else:
        values = []
        for field in ("msisdn", "phone_a", "phone_b"):
            field_values = ctx.get(f"{field}_values") or [ctx.get(field)]
            for value in field_values:
                if value and value not in values:
                    values.append(value)
        if not values:
            raise ValueError("В заявке не найдено ни одного номера")
        replacement_sets = [
            [
                (
                    slots[0]["match_value"],
                    _replacement_for("number", slots[0]["strategy"], value),
                )
            ]
            for value in values
        ]

    links = []
    for replacements in replacement_sets:
        generated = (
            _grafana_links(source, replacements, ctx)
            if source["platform"] == "grafana"
            else [_opensearch_link(source, replacements, ctx)]
        )
        for link in generated:
            if link not in links:
                links.append(link)
    return links


def build_product_links(product, level, ctx, call_uuid=None, path=None):
    links = {}
    titles = {}
    errors = []
    for source in list_sources(product=product, level=level, path=path, enabled_only=True):
        titles[source["id"]] = source["name"]
        try:
            generated = build_source_links(source, ctx, call_uuid=call_uuid)
        except (KeyError, TypeError, ValueError) as error:
            errors.append(f"{source['name']}: {error}")
            continue
        if generated:
            links[source["id"]] = generated
    return links, titles, errors
