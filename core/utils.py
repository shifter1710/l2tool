import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID


def hash_phone(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()[:16]


def normalize_uuid(value: str) -> str:
    try:
        return str(UUID(str(value).strip()))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("Некорректный UUID звонка") from error


def atomic_write_text(path, text):
    """Атомарная запись текста: временный файл рядом с целью, fsync, 0600, replace.

    Родительский каталог должен существовать (при необходимости его создаёт
    вызывающий код). Временный файл удаляется при любом сбое.
    """
    path = Path(path)
    tmp_path = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_file.write(text)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
            tmp_path = Path(tmp_file.name)
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(path)
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


def atomic_write_json(path, data):
    """Атомарная запись JSON в формате локальных хранилищ (indent=2 + перевод строки)."""
    atomic_write_text(
        path,
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
    )


def rotate_backups(directory, pattern, keep):
    """Оставить в каталоге последние `keep` копий с именами по шаблону pattern."""
    directory = Path(directory)
    if not directory.is_dir():
        return
    files = sorted(
        (item for item in directory.iterdir() if pattern.fullmatch(item.name)),
        key=lambda item: item.name,
    )
    for stale in files[:-keep]:
        stale.unlink(missing_ok=True)
