import json
import os
import re
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

BACKUP_KEEP = 20
BACKUP_NAME_PATTERN = re.compile(
    r"^diagnostic_sources\.(\d{8})-(\d{6})(?:-\d+)?\.json$"
)


def backups_dir(path=None):
    from core.dynamic_sources import STORE_PATH

    store = Path(path or STORE_PATH)
    return store.parent / "backups"


def _backup_files(directory):
    if not directory.is_dir():
        return []
    return sorted(
        (item for item in directory.iterdir() if BACKUP_NAME_PATTERN.fullmatch(item.name)),
        key=lambda item: item.name,
    )


def _write_file_atomic(target, content):
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    os.chmod(temporary_path, 0o600)
    temporary_path.replace(target)


def create_backup(path=None):
    """Сохранить копию текущего хранилища в backups/ и удалить старые копии."""
    from core.dynamic_sources import STORE_PATH

    store = Path(path or STORE_PATH)
    if not store.exists():
        return None
    directory = backups_dir(store)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = directory / f"diagnostic_sources.{stamp}.json"
    suffix = 0
    while target.exists():
        suffix += 1
        target = directory / f"diagnostic_sources.{stamp}-{suffix}.json"
    _write_file_atomic(target, store.read_text(encoding="utf-8"))
    _rotate(directory)
    return target.name


def _rotate(directory):
    files = _backup_files(directory)
    for stale in files[:-BACKUP_KEEP]:
        stale.unlink(missing_ok=True)


def _parse_stamp(name):
    match = BACKUP_NAME_PATTERN.fullmatch(name)
    if not match:
        return None
    try:
        return datetime.strptime(
            f"{match.group(1)}-{match.group(2)}", "%Y%m%d-%H%M%S"
        )
    except ValueError:
        return None


def list_backups(path=None):
    """Список копий (новые первыми): имя, время, количество блоков."""
    from core.dynamic_sources import STORE_PATH

    store = Path(path or STORE_PATH)
    result = []
    for item in reversed(_backup_files(backups_dir(store))):
        stamp = _parse_stamp(item.name)
        if stamp is None:
            continue
        try:
            content = item.read_text(encoding="utf-8")
        except OSError:
            continue
        blocks = None
        try:
            data = json.loads(content)
            if isinstance(data, dict) and isinstance(data.get("sources"), list):
                blocks = len(data["sources"])
        except (json.JSONDecodeError, ValueError):
            blocks = None
        result.append({"name": item.name, "created": stamp, "blocks": blocks})
    return result


def restore_backup(name, path=None):
    """Заменить хранилище содержимым копии (с бэкапом текущего состояния)."""
    from core.dynamic_sources import STORE_PATH, load_store, write_store

    name = str(name or "").strip()
    if not BACKUP_NAME_PATTERN.fullmatch(name):
        raise ValueError("Некорректное имя резервной копии")
    store = Path(path or STORE_PATH)
    backup_path = backups_dir(store) / name
    if not backup_path.is_file():
        raise ValueError("Резервная копия не найдена")
    try:
        data = load_store(backup_path)
    except (OSError, ValueError) as error:
        raise ValueError(f"Не удалось прочитать копию: {error}") from error
    create_backup(store)
    write_store(data, store)
