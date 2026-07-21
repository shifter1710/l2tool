import re
import sys
from datetime import datetime

EMPTY_PHONE_VALUES = {
    "",
    "-",
    "все",
    "все звонки",
    "все номера",
    "любой",
    "любой номер",
    "не знает",
    "не указал",
    "не указан",
    "неизвестно",
    "нет",
}
EMPTY_PHONE_PREFIXES = (
    "все звонки",
    "все номера не запис",
)


def find_field(text: str, patterns: list[str]):
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(1).strip()
    return None


def is_empty_phone_value(value: str | None):
    if value is None:
        return True

    normalized = value.strip().lower()
    return normalized in EMPTY_PHONE_VALUES or normalized.startswith(EMPTY_PHONE_PREFIXES)


def normalize_phone(value: str | None, allow_landline: bool = False):
    if is_empty_phone_value(value):
        return None

    digits = re.sub(r"\D", "", value)

    if len(digits) == 10:
        digits = "7" + digits
    elif len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]

    if len(digits) == 11 and digits.startswith("7"):
        return digits

    print(f"[WARN] Не удалось нормализовать номер: {value}", file=sys.stderr)
    return None


def parse_event_datetimes(value: str | None):
    if not value:
        return []

    date_match = re.search(
        r"(?<!\d)(?P<day>\d{2})\.(?P<month>\d{2})(?:\.(?P<year>\d{4}))?(?!\d)",
        value,
    )
    if not date_match:
        return []

    year = date_match.group("year") or str(datetime.now().year)
    date_value = f"{date_match.group('day')}.{date_match.group('month')}.{year}"

    try:
        event_date = datetime.strptime(date_value, "%d.%m.%Y").date()
    except ValueError:
        return []

    remainder = value[date_match.end():]
    time_matches = re.finditer(
        r"(?<!\d)(?P<hour>[01]?\d|2[0-3])[:.-](?P<minute>[0-5]\d)"
        r"(?:[:.-](?P<second>[0-5]\d))?(?!\d)",
        remainder,
    )

    return [
        datetime.combine(
            event_date,
            datetime.strptime(
                f"{m.group('hour')}:{m.group('minute')}:{m.group('second') or '00'}",
                "%H:%M:%S",
            ).time(),
        )
        for m in time_matches
    ]


def parse_datetime_value(value: str):
    event_datetimes = parse_event_datetimes(value)
    if event_datetimes:
        return event_datetimes[0]

    value = value.strip()
    m = re.search(
        r"(?P<date>\d{2}\.\d{2}\.\d{4})"
        r"(?:\s*,\s*|\s+в\s+|\s+)"
        r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)",
        value,
        re.IGNORECASE,
    )
    if m:
        value = f"{m.group('date')} {m.group('time')}"

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

    return None


def parse_date_value(value: str | None):
    if not value:
        return None

    value = value.strip()
    if not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", value):
        return None

    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        return None


def parse_time_value(value: str | None):
    if not value:
        return None

    value = value.strip().replace("-", ":").replace(".", ":")
    if not re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", value):
        return None

    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue

    return None


def combine_event_datetime(raw_value, event_date, event_clock):
    event_datetime = parse_datetime_value(raw_value) if raw_value else None
    if event_datetime:
        return event_datetime

    if event_date and event_clock:
        return datetime.combine(event_date, event_clock)

    return None


def parse(text: str):
    phone_a_raw = find_field(text, [
        r"Номер звонящего\s*\(А\)\s*[:：]\s*(.+)",
        r"Номер звонящего\s*[:：]\s*(.+)",
        r"Номер А\s*[:：]\s*(.+)",
    ])

    phone_b_raw = find_field(text, [
        r"Номер принимающего звонок\s*\(Б\)\s*[:：]\s*(.+)",
        r"Номер принимающего звонок\s*Б\s*[:：]\s*(.+)",
        r"Номер принимающего\s*[:：]\s*(.+)",
        r"Номер Б\s*[:：]\s*(.+)",
        r"^\s*Б\s*[:：]\s*(.+)",
        r"callee\s*[:：]\s*(.+)",
        r"number_b\s*[:：]\s*(.+)",
    ])

    msisdn_raw = find_field(text, [
        r"Номер клиента\s*\(msisdn\)\s*[:：]\s*(.+)",
        r"msisdn\s*[:：]\s*(.+)",
        r"Номер клиента\s*[:：]\s*(.+)",
    ])

    datetime_raw = find_field(text, [
        r"Дата и время проблемного звонка\s*[:：]\s*(.+)",
        r"Дата и время звонка\s*[:：]\s*(.+)",
        r"Время события\s*[:：]\s*(.+)",
    ])

    date_raw = find_field(text, [
        r"Дата проблемного звонка\s*[:：]\s*(.+)",
        r"Дата звонка\s*[:：]\s*(.+)",
        r"Дата события\s*[:：]\s*(.+)",
        r"Дата\s*[:：]\s*(.+)",
    ])

    time_raw = find_field(text, [
        r"Время проблемного звонка\s*[:：]\s*(.+)",
        r"Время звонка\s*[:：]\s*(.+)",
        r"Время\s*[:：]\s*(.+)",
    ])

    region = find_field(text, [
        r"Местонахождение абонента\s*[:：]\s*(.+)",
        r"Местонахождение\s*[:：]\s*(.+)",
        r"Регион\s*[:：]\s*(.+)",
    ])

    event_date = parse_date_value(date_raw) or parse_date_value(datetime_raw)
    event_clock = parse_time_value(time_raw)
    event_datetimes = parse_event_datetimes(datetime_raw)
    event_datetime = event_datetimes[0] if event_datetimes else combine_event_datetime(
        datetime_raw,
        event_date,
        event_clock,
    )

    if event_datetime and not event_date:
        event_date = event_datetime.date()

    if not event_datetimes and event_datetime:
        event_datetimes = [event_datetime]

    phone_fields = {
        "msisdn": msisdn_raw,
        "phone_a": phone_a_raw,
        "phone_b": phone_b_raw,
    }
    normalized_phones = {
        field: normalize_phone(raw_value, allow_landline=(field == "phone_b"))
        for field, raw_value in phone_fields.items()
    }

    return {
        "phone_a": normalized_phones["phone_a"],
        "phone_a_raw": phone_a_raw,
        "phone_b": normalized_phones["phone_b"],
        "phone_b_raw": phone_b_raw,
        "number_b": normalized_phones["phone_b"],
        "number_b_raw": phone_b_raw,
        "callee": normalized_phones["phone_b"],
        "callee_raw": phone_b_raw,
        "msisdn": normalized_phones["msisdn"],
        "msisdn_raw": msisdn_raw,
        "phone_fields": phone_fields,
        "normalized_phones": normalized_phones,
        "event_date": event_date,
        "event_clock": event_clock,
        "event_time": event_datetime,
        "event_datetimes": event_datetimes,
        "region": region,
    }
