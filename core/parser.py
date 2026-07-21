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

DATE_PATTERN = re.compile(
    r"(?<!\d)(?P<day>\d{1,2})(?P<separator>[.,/])(?P<month>\d{1,2})"
    r"(?:\2(?P<year>\d{2}|\d{4}))?(?!\d)"
)
DATE_RANGE_PATTERN = re.compile(
    r"(?<!\d)\d{1,2}[.,/]\d{1,2}\.?\s*-\s*\d{1,2}[.,/]\d{1,2}(?!\d)"
)
TIME_PATTERN = re.compile(
    r"(?<!\d)(?P<hour>[01]?\d|2[0-3])[-:.,;/](?P<minute>[0-5]\d)"
    r"(?:[-:.,;/](?P<second>[0-5]\d))?(?!\d)"
)
HOUR_RANGE_PATTERN = re.compile(
    r"\bс\s+(?P<start>[01]?\d|2[0-3])(?:[:.,](?P<start_minute>[0-5]\d))?"
    r"\s+до\s+(?P<end>[01]?\d|2[0-3])(?:[:.,](?P<end_minute>[0-5]\d))?\b",
    re.IGNORECASE,
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


def _event_date_match(value: str | None):
    if not value or DATE_RANGE_PATTERN.search(value):
        return None, None

    matches = list(DATE_PATTERN.finditer(value))
    matches.sort(key=lambda match: match.group("year") is None)

    for match in matches:
        raw_year = match.group("year")
        year = datetime.now().year if raw_year is None else int(raw_year)
        if raw_year and len(raw_year) == 2:
            year += 2000

        try:
            event_date = datetime(year, int(match.group("month")), int(match.group("day"))).date()
        except ValueError:
            continue

        return match, event_date

    return None, None


def parse_event_time_range(value: str | None):
    date_match, event_date = _event_date_match(value)
    if not date_match or not event_date:
        return None

    range_match = HOUR_RANGE_PATTERN.search(value)
    if not range_match:
        return None

    start = datetime.combine(
        event_date,
        datetime.strptime(
            f"{range_match.group('start')}:{range_match.group('start_minute') or '00'}",
            "%H:%M",
        ).time(),
    )
    end = datetime.combine(
        event_date,
        datetime.strptime(
            f"{range_match.group('end')}:{range_match.group('end_minute') or '00'}",
            "%H:%M",
        ).time(),
    )
    return (start, end) if start < end else None


def parse_event_datetimes(value: str | None):
    date_match, event_date = _event_date_match(value)
    if not date_match or not event_date or parse_event_time_range(value):
        return []

    without_date = value[:date_match.start()] + " " + value[date_match.end():]
    time_matches = TIME_PATTERN.finditer(without_date)

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
    _match, event_date = _event_date_match(value)
    return event_date


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
    event_time_range = parse_event_time_range(datetime_raw)
    event_datetimes = parse_event_datetimes(datetime_raw)
    if event_time_range:
        event_datetime = event_time_range[0]
    else:
        event_datetime = event_datetimes[0] if event_datetimes else combine_event_datetime(
            datetime_raw,
            event_date,
            event_clock,
        )

    if event_datetime and not event_date:
        event_date = event_datetime.date()

    if not event_time_range and not event_datetimes and event_datetime:
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
        "event_time_range": event_time_range,
        "event_datetimes": event_datetimes,
        "region": region,
    }
