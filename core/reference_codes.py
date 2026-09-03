"""Локальный справочник «код → расшифровка»; данные не попадают в Git."""

import json
import logging
import os
import re
import threading
from pathlib import Path
from tempfile import NamedTemporaryFile

ROOT_DIR = Path(__file__).resolve().parents[1]
STORE_PATH = ROOT_DIR / "reference_codes.json"
MAX_FILE_SIZE = 256 * 1024
MAX_TEXT_LENGTH = 500
MAX_CODE_LENGTH = 16
MAX_GROUP_NAME_LENGTH = 80
MAX_ENTRIES = 1000
_WRITE_LOCK = threading.RLock()
_LOAD_ERROR_LOGGED = threading.Event()
LOGGER = logging.getLogger(__name__)


def validate_store(data):
    """Проверить структуру «группа → {код: текст}»; вернуть нормализованную копию."""
    if not isinstance(data, dict):
        raise ValueError("Справочник должен быть JSON-объектом «группа → коды»")
    groups = {}
    total = 0
    for raw_group, raw_codes in data.items():
        group = str(raw_group).strip()
        if not group or len(group) > MAX_GROUP_NAME_LENGTH:
            raise ValueError(
                f"Название группы справочника: от 1 до {MAX_GROUP_NAME_LENGTH} символов"
            )
        if not isinstance(raw_codes, dict):
            raise ValueError(f"Группа «{group}» должна быть объектом «код → текст»")
        codes = {}
        for raw_code, raw_text in raw_codes.items():
            code = str(raw_code).strip()
            text = str(raw_text).strip()
            if not code or len(code) > MAX_CODE_LENGTH:
                raise ValueError(
                    f"Код «{raw_code}» в группе «{group}»: от 1 до {MAX_CODE_LENGTH} символов"
                )
            if not text or len(text) > MAX_TEXT_LENGTH:
                raise ValueError(
                    f"Расшифровка кода {group} {code}: от 1 до {MAX_TEXT_LENGTH} символов"
                )
            total += 1
            if total > MAX_ENTRIES:
                raise ValueError(
                    f"В справочнике не может быть больше {MAX_ENTRIES} записей"
                )
            codes[code] = text
        groups[group] = codes
    return groups


def load_store(path=None):
    path = Path(path or STORE_PATH)
    if not path.exists():
        return {}
    try:
        if path.stat().st_size > MAX_FILE_SIZE:
            raise ValueError(
                f"Файл справочника превышает {MAX_FILE_SIZE // 1024} КБ"
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        return validate_store(data)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        if not _LOAD_ERROR_LOGGED.is_set():
            _LOAD_ERROR_LOGGED.set()
            LOGGER.warning("Справочник кодов не загружен (%s): %s", path.name, error)
        return {}


def write_store(groups, path=None):
    path = Path(path or STORE_PATH)
    validated = validate_store(groups)
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
                json.dump(validated, temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.chmod(temporary_path, 0o600)
            temporary_path.replace(path)
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()


def import_store(content, path=None):
    """Заменить справочник целиком; вернуть количество записей."""
    try:
        data = json.loads(content)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Файл должен содержать корректный JSON") from error
    if len(content.encode("utf-8")) > MAX_FILE_SIZE:
        raise ValueError(f"Файл справочника превышает {MAX_FILE_SIZE // 1024} КБ")
    groups = validate_store(data)
    write_store(groups, path=path)
    return sum(len(codes) for codes in groups.values())


def export_store(path=None):
    """Текущий файл справочника для скачивания; пустой JSON, если файла нет."""
    path = Path(path or STORE_PATH)
    if not path.exists():
        return json.dumps(load_store(path), ensure_ascii=False, indent=2) + "\n"
    return path.read_text(encoding="utf-8")


def find_codes(text, path=None):
    """Найти в тексте коды из справочника: «Группа 10», «Группа: 10», «Группа=10»."""
    groups = load_store(path)
    if not groups or not text:
        return []
    matches = []
    for group, codes in groups.items():
        pattern = re.compile(
            rf"(?i)\b{re.escape(group)}\s*[:=]?\s*([0-9]{{1,3}})\b"
        )
        for match in pattern.finditer(text):
            code = match.group(1)
            if code in codes:
                matches.append((match.start(), group, code, codes[code]))
    matches.sort(key=lambda item: item[0])
    hints = []
    seen = set()
    for _position, group, code, text_value in matches:
        key = (group, code)
        if key in seen:
            continue
        seen.add(key)
        hints.append({"group": group, "code": code, "text": text_value})
    return hints
