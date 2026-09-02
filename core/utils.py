import hashlib
from uuid import UUID


def hash_phone(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()[:16]


def normalize_uuid(value: str) -> str:
    try:
        return str(UUID(str(value).strip()))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("Некорректный UUID звонка") from error
