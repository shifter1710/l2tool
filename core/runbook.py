"""Локальный ранбук «симптом → где смотреть»; содержимое не попадает в Git."""

import json
import logging
import os
import re
import secrets
import threading
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

ROOT_DIR = Path(__file__).resolve().parents[1]
STORE_PATH = ROOT_DIR / "runbook.json"
MAX_FILE_SIZE = 256 * 1024
MAX_SYMPTOM_LENGTH = 200
MAX_NOTE_LENGTH = 500
MAX_ID_LENGTH = 64
MAX_CASES = 50
MAX_STEPS = 15
BACKUP_KEEP = 20
BACKUP_NAME_PATTERN = re.compile(r"^runbook\.(\d{8})-(\d{6})(?:-\d+)?\.json$")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_WRITE_LOCK = threading.RLock()
_LOAD_ERROR_LOGGED = threading.Event()
LOGGER = logging.getLogger(__name__)


def validate_case(raw):
    """Проверить кейс {id, symptom, steps}; вернуть нормализованную копию."""
    if not isinstance(raw, dict):
        raise ValueError("Кейс ранбука должен быть JSON-объектом")
    case_id = str(raw.get("id", "")).strip()
    if not case_id or len(case_id) > MAX_ID_LENGTH:
        raise ValueError(f"Идентификатор кейса: от 1 до {MAX_ID_LENGTH} символов")
    if not ID_PATTERN.fullmatch(case_id):
        raise ValueError("Идентификатор кейса: строчные латинские буквы, цифры и дефис")
    symptom = str(raw.get("symptom", "")).strip()
    if not symptom or len(symptom) > MAX_SYMPTOM_LENGTH:
        raise ValueError(f"Симптом: от 1 до {MAX_SYMPTOM_LENGTH} символов")
    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("У кейса должен быть хотя бы один шаг")
    if len(raw_steps) > MAX_STEPS:
        raise ValueError(f"В кейсе не может быть больше {MAX_STEPS} шагов")

    steps = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            raise ValueError(f"Шаг {index}: ожидается объект с полями source и note")
        note = str(raw_step.get("note", "")).strip()
        if not note or len(note) > MAX_NOTE_LENGTH:
            raise ValueError(f"Шаг {index}: пояснение от 1 до {MAX_NOTE_LENGTH} символов")
        source = raw_step.get("source")
        if source is None or str(source).strip() == "":
            source = None
        else:
            source = str(source).strip()
            if len(source) > MAX_ID_LENGTH:
                raise ValueError(
                    f"Шаг {index}: идентификатор блока до {MAX_ID_LENGTH} символов"
                )
        steps.append({"source": source, "note": note})
    return {"id": case_id, "symptom": symptom, "steps": steps}


def validate_store(data):
    """Проверить массив кейсов; вернуть нормализованную копию."""
    if not isinstance(data, list):
        raise ValueError("Ранбук должен быть JSON-массивом кейсов")
    if len(data) > MAX_CASES:
        raise ValueError(f"В ранбуке не может быть больше {MAX_CASES} кейсов")
    cases = []
    seen = set()
    for index, raw in enumerate(data, start=1):
        try:
            case = validate_case(raw)
        except ValueError as error:
            raise ValueError(f"Кейс {index}: {error}") from error
        if case["id"] in seen:
            raise ValueError(f"Кейс {index}: идентификатор «{case['id']}» повторяется")
        seen.add(case["id"])
        cases.append(case)
    return cases


def load_store(path=None):
    path = Path(path or STORE_PATH)
    if not path.exists():
        return []
    try:
        if path.stat().st_size > MAX_FILE_SIZE:
            raise ValueError(f"Файл ранбука превышает {MAX_FILE_SIZE // 1024} КБ")
        data = json.loads(path.read_text(encoding="utf-8"))
        return validate_store(data)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        if not _LOAD_ERROR_LOGGED.is_set():
            _LOAD_ERROR_LOGGED.set()
            LOGGER.warning("Ранбук не загружен (%s): %s", path.name, error)
        return []


def write_store(cases, path=None):
    path = Path(path or STORE_PATH)
    validated = validate_store(cases)
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


def create_backup(path=None):
    """Сохранить копию текущего ранбука в backups/ и удалить старые копии."""
    path = Path(path or STORE_PATH)
    if not path.exists():
        return None
    directory = path.parent / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = directory / f"runbook.{stamp}.json"
    suffix = 0
    while target.exists():
        suffix += 1
        target = directory / f"runbook.{stamp}-{suffix}.json"
    content = path.read_text(encoding="utf-8")
    temporary_path = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=directory,
            prefix=".runbook.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.chmod(temporary_path, 0o600)
        temporary_path.replace(target)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
    stale = sorted(
        item for item in directory.iterdir() if BACKUP_NAME_PATTERN.fullmatch(item.name)
    )
    for item in stale[:-BACKUP_KEEP]:
        item.unlink(missing_ok=True)
    return target.name


def save_case(values, case_id=None, path=None):
    """Добавить или обновить кейс; перед изменением — копия в бэкапы."""
    raw = dict(values)
    if case_id:
        raw["id"] = case_id
    elif not str(raw.get("id", "")).strip():
        raw["id"] = f"case-{secrets.token_hex(4)}"
    case = validate_case(raw)
    with _WRITE_LOCK:
        cases = load_store(path)
        if len(cases) >= MAX_CASES and not any(
            item["id"] == case["id"] for item in cases
        ):
            raise ValueError(f"В ранбуке не может быть больше {MAX_CASES} кейсов")
        existing = next((item for item in cases if item["id"] == case["id"]), None)
        create_backup(path)
        if existing is None:
            cases.append(case)
        else:
            cases[cases.index(existing)] = case
        write_store(cases, path)
    return case


def delete_case(case_id, path=None):
    with _WRITE_LOCK:
        cases = load_store(path)
        remaining = [item for item in cases if item["id"] != case_id]
        if len(remaining) == len(cases):
            raise ValueError("Кейс ранбука не найден")
        create_backup(path)
        write_store(remaining, path)


def find_case(case_id, path=None):
    return next(
        (item for item in load_store(path) if item["id"] == case_id), None
    )


def import_store(content, path=None):
    """Заменить ранбук целиком; вернуть количество кейсов."""
    try:
        data = json.loads(content)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Файл должен содержать корректный JSON") from error
    if len(content.encode("utf-8")) > MAX_FILE_SIZE:
        raise ValueError(f"Файл ранбука превышает {MAX_FILE_SIZE // 1024} КБ")
    cases = validate_store(data)
    create_backup(path)
    write_store(cases, path=path)
    return len(cases)


def export_store(path=None):
    """Текущий файл ранбука для скачивания; пустой JSON, если файла нет."""
    path = Path(path or STORE_PATH)
    if not path.exists():
        return json.dumps(load_store(path), ensure_ascii=False, indent=2) + "\n"
    return path.read_text(encoding="utf-8")
