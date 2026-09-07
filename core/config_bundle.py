"""Полный бандл конфигураций: выгрузка и загрузция всех хранилищ разом.

В бандл входят все локальные настройки l2tool:
- diagnostic_sources.json — продукты, диагностические блоки и номера Секретаря;
- reference_codes.json — справочник кодов;
- runbook.json — ранбук «куда смотреть»;
- config.toml — статические сервисы и значения по умолчанию (если файл есть).

Отдельные части импортируются теми же правилами, что и одиночная загрузка:
блоки добавляются к существующим (дубликаты пропускаются), справочник и
ранбук заменяются целиком, config.toml перезаписывается после проверки
с бэкапом прежнего файла.
"""

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from core import reference_codes, runbook
from core.config import CONFIG_PATH, parse_simple_toml
from core.dynamic_sources import (
    available_products,
    create_product,
    import_sources,
    load_store,
    normalize_secretary_numbers,
    save_call_history_secretary_numbers,
)
from core.url_guard import find_config_issues

BUNDLE_VERSION = 1
BUNDLE_MARKER = "configs"
MAX_BUNDLE_SIZE = 8 * 1024 * 1024
CONFIG_BACKUP_KEEP = 5


def build_bundle():
    """Собрать бандл со всеми хранилищами; пустые — пропускаются."""
    bundle = {
        "l2tool": BUNDLE_MARKER,
        "version": BUNDLE_VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "stores": {},
    }
    try:
        bundle["stores"]["diagnostic_sources"] = load_store()
    except (OSError, ValueError):
        pass
    try:
        bundle["stores"]["reference_codes"] = reference_codes.load_store()
    except (OSError, ValueError):
        pass
    try:
        bundle["stores"]["runbook"] = runbook.load_store()
    except (OSError, ValueError):
        pass
    try:
        if CONFIG_PATH.exists():
            content = CONFIG_PATH.read_text(encoding="utf-8")
            issues = find_config_issues(content)
            if issues:
                # config.toml с секретами не включаем в файл переноса
                bundle["skipped"] = {"config_toml": "; ".join(issues[:2])}
            else:
                bundle["config_toml"] = content
    except OSError:
        pass
    return bundle


def _ensure_bundle_products(store_part, report):
    """Создать недостающие продукты из бандла, чтобы блоки могли прицепиться."""
    products = store_part.get("products")
    if not isinstance(products, list):
        return
    known = available_products()
    for entry in products:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        if not key or key in known:
            continue
        try:
            create_product(key, str(entry.get("title") or key), entry.get("color"))
            known.append(key)
            report["notes"].append(f"Создан продукт «{key}»")
        except ValueError as error:
            report["errors"].append(f"Продукт «{key}» из бандла: {error}")


def _import_sources_part(store_part, report):
    _ensure_bundle_products(store_part, report)
    section = store_part.get("call_history")
    numbers_text = None
    if isinstance(section, dict) and "secretary_numbers" in section:
        numbers = section.get("secretary_numbers")
        items = numbers if isinstance(numbers, list) else []
        numbers_text = "\n".join(str(item) for item in items)

    # Номера Секретаря проверяем до применения блоков — иначе ошибка
    # в номерах оставит наполовину применённый бандл
    normalized_numbers = (
        None if numbers_text is None else normalize_secretary_numbers(numbers_text)
    )

    content = json.dumps(store_part, ensure_ascii=False)
    result = import_sources(content)
    report["stores"]["diagnostic_sources"] = (
        f"блоков добавлено {result['added']}, пропущено {result['skipped']}"
    )
    if normalized_numbers is not None:
        save_call_history_secretary_numbers(numbers_text)
        report["stores"]["secretary_numbers"] = (
            f"номеров Секретаря сохранено {len(normalized_numbers)}"
        )


def import_config_toml(text):
    """Заменить config.toml после проверки; прежний — в бэкап рядом с файлом."""
    content = str(text)
    if not content.strip():
        raise ValueError("config.toml пуст")
    if len(content.encode("utf-8")) > MAX_BUNDLE_SIZE:
        raise ValueError("config.toml слишком велик")
    issues = find_config_issues(content)
    if issues:
        raise ValueError(
            "config.toml не принят — секреты и посторонние ссылки запрещены: "
            + "; ".join(issues)
        )
    try:
        import tomllib

        tomllib.loads(content)
    except ModuleNotFoundError:
        # Python 3.10: tomllib нет — проверяем упрощённым парсером, чтобы
        # мусор не записывался в config.toml молча
        try:
            parse_simple_toml(content)
        except ValueError as error:
            raise ValueError(f"config.toml не разбирается как TOML: {error}") from error
    except (TypeError, ValueError) as error:
        raise ValueError(f"config.toml не разбирается как TOML: {error}") from error

    path = Path(CONFIG_PATH)
    if path.exists():
        _backup_config(path)
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    os.chmod(temporary_path, 0o600)
    temporary_path.replace(path)
    return True


def _backup_config(path):
    backups_dir = path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backups_dir / f"config.toml.{stamp}.bak"
    suffix = 0
    while target.exists():
        suffix += 1
        target = backups_dir / f"config.toml.{stamp}-{suffix}.bak"
    shutil.copy2(path, target)
    _rotate_config_backups(backups_dir)


def _rotate_config_backups(backups_dir):
    files = sorted(
        (item for item in backups_dir.iterdir() if _CONFIG_BACKUP_PATTERN.fullmatch(item.name)),
        key=lambda item: item.name,
    )
    for stale in files[:-CONFIG_BACKUP_KEEP]:
        stale.unlink(missing_ok=True)


_CONFIG_BACKUP_PATTERN = re.compile(r"^config\.toml\.\d{8}-\d{6}(?:-\d+)?\.bak$")


def import_bundle(content):
    """Разобрать и применить бандл; вернуть отчёт по каждому хранилищу."""
    if not isinstance(content, str):
        raise ValueError("Файл бандла должен быть текстовым JSON")
    if len(content.encode("utf-8")) > MAX_BUNDLE_SIZE:
        raise ValueError("Файл бандла превышает 8 МБ")
    try:
        bundle = json.loads(content)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Файл бандла должен содержать корректный JSON") from error
    except RecursionError as error:
        raise ValueError("JSON бандла вложен слишком глубоко") from error
    if not isinstance(bundle, dict) or bundle.get("l2tool") != BUNDLE_MARKER:
        raise ValueError(
            "Это не бандл l2tool: скачайте «Все конфиги» на странице настроек"
        )
    version = bundle.get("version")
    if version != BUNDLE_VERSION:
        raise ValueError(f"Неподдерживаемая версия бандла: {version}")

    stores = bundle.get("stores")
    if not isinstance(stores, dict):
        raise ValueError("В бандле нет секции stores")

    report = {"stores": {}, "errors": [], "notes": []}

    sources_part = stores.get("diagnostic_sources")
    if isinstance(sources_part, dict):
        try:
            _import_sources_part(sources_part, report)
        except (OSError, ValueError) as error:
            report["errors"].append(f"Диагностические блоки: {error}")

    reference_part = stores.get("reference_codes")
    if isinstance(reference_part, dict):
        try:
            count = reference_codes.import_store(
                json.dumps(reference_part, ensure_ascii=False)
            )
            report["stores"]["reference_codes"] = f"справочник заменён: {count} записей"
        except (OSError, ValueError) as error:
            report["errors"].append(f"Справочник кодов: {error}")

    runbook_part = stores.get("runbook")
    if isinstance(runbook_part, list):
        try:
            count = runbook.import_store(json.dumps(runbook_part, ensure_ascii=False))
            report["stores"]["runbook"] = f"ранбук заменён: {count} кейсов"
        except (OSError, ValueError) as error:
            report["errors"].append(f"Ранбук: {error}")

    config_text = bundle.get("config_toml")
    if isinstance(config_text, str) and config_text.strip():
        try:
            import_config_toml(config_text)
            report["stores"]["config_toml"] = "config.toml заменён (копия прежнего в backups/)"
        except (OSError, ValueError) as error:
            report["errors"].append(f"config.toml: {error}")

    return report


def bundle_summary():
    """Короткая сводка о составе бандла для интерфейса."""
    stores = []
    try:
        sources = load_store().get("sources", [])
        stores.append(f"блоки ({len(sources)})")
    except (OSError, ValueError):
        pass
    try:
        stores.append(f"справочник ({len(reference_codes.load_store())} групп)")
    except (OSError, ValueError):
        pass
    try:
        stores.append(f"ранбук ({len(runbook.load_store())} кейсов)")
    except (OSError, ValueError):
        pass
    if CONFIG_PATH.exists():
        try:
            issues = find_config_issues(CONFIG_PATH.read_text(encoding="utf-8"))
        except OSError:
            issues = []
        if issues:
            stores.append("config.toml пропущен — в нём найден секрет или посторонняя ссылка")
        else:
            stores.append("config.toml")
    return " · ".join(stores) if stores else "хранилища пусты"
