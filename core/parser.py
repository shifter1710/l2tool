import re
from datetime import datetime


def find_field(text: str, patterns: list[str]):
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(1).strip()
    return None


def normalize_phone(value: str | None):
    if not value:
        return None

    digits = re.sub(r"\D", "", value)

    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]

    if len(digits) == 11 and digits.startswith("7"):
        return digits

    return None


def parse_time_value(value: str):
    value = value.strip()

    for fmt in (
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    raise ValueError(f"Bad time: {value}")


def parse(text: str):
    phone_a_raw = find_field(text, [
        r"Номер звонящего\s*\(А\)\s*[:：]\s*(.+)",
        r"Номер звонящего\s*[:：]\s*(.+)",
        r"Номер А\s*[:：]\s*(.+)",
    ])

    phone_b_raw = find_field(text, [
        r"Номер принимающего звонок\s*\(Б\)\s*[:：]\s*(.+)",
        r"Номер принимающего\s*[:：]\s*(.+)",
        r"Номер Б\s*[:：]\s*(.+)",
    ])

    msisdn_raw = find_field(text, [
        r"Номер клиента\s*\(msisdn\)\s*[:：]\s*(.+)",
        r"msisdn\s*[:：]\s*(.+)",
        r"Номер клиента\s*[:：]\s*(.+)",
    ])

    time_raw = find_field(text, [
        r"Дата и время проблемного звонка\s*[:：]\s*(.+)",
        r"Дата и время звонка\s*[:：]\s*(.+)",
        r"Время события\s*[:：]\s*(.+)",
    ])

    region = find_field(text, [
        r"Местонахождение абонента\s*[:：]\s*(.+)",
        r"Местонахождение\s*[:：]\s*(.+)",
        r"Регион\s*[:：]\s*(.+)",
    ])

    return {
        "phone_a": normalize_phone(phone_a_raw),
        "phone_b": normalize_phone(phone_b_raw),
        "msisdn": normalize_phone(msisdn_raw),
        "event_time": parse_time_value(time_raw) if time_raw else None,
        "region": region,
    }
