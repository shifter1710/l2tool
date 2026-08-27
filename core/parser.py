import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.ticket_fields import extract_ticket_fields
from core.timezones import resolve_timezone

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
RUSSIAN_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
RUSSIAN_DATE_PATTERN = re.compile(
    r"(?<!\d)(?P<day>\d{1,2})\s+(?P<month>" + "|".join(RUSSIAN_MONTHS) + r")"
    r"\s+(?P<year>\d{4})(?!\d)",
    re.IGNORECASE,
)
COMPACT_DATE_PATTERN = re.compile(
    r"(?<!\d)(?P<day>\d{2})(?P<month>\d{2})(?P<year>\d{4})(?!\d)"
)
GENERAL_PROBLEM_PATTERN = re.compile(
    r"все\s+время|любые\s+звонки|\bвчера\b",
    re.IGNORECASE,
)


def find_field(text: str, patterns: list[str]):
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
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


def extract_phone_values(value: str | None, allow_short: bool = False):
    if is_empty_phone_value(value):
        return []

    candidates = re.findall(r"(?<!\d)(?:[78]\d{10}|\d{10}|\d{7})(?!\d)", value)
    values = []
    for candidate in candidates:
        normalized = normalize_phone(candidate)
        if normalized is None and allow_short and len(candidate) == 7:
            normalized = candidate
        if normalized and normalized not in values:
            values.append(normalized)

    return values


def extract_partial_phone(value: str | None):
    if not value:
        return None

    match = re.search(r"\+?7(?P<prefix>\d{3})\.{2,}", value)
    return match.group("prefix") if match else None


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

        return (match.start(), match.end()), event_date

    russian_match = RUSSIAN_DATE_PATTERN.search(value)
    if russian_match:
        try:
            event_date = datetime(
                int(russian_match.group("year")),
                RUSSIAN_MONTHS[russian_match.group("month").lower()],
                int(russian_match.group("day")),
            ).date()
        except ValueError:
            pass
        else:
            return (russian_match.start(), russian_match.end()), event_date

    compact_match = COMPACT_DATE_PATTERN.search(value)
    if compact_match:
        try:
            event_date = datetime(
                int(compact_match.group("year")),
                int(compact_match.group("month")),
                int(compact_match.group("day")),
            ).date()
        except ValueError:
            pass
        else:
            return (compact_match.start(), compact_match.end()), event_date

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

    without_date = value[:date_match[0]] + " " + value[date_match[1]:]
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


def parse(text: str, now: datetime | None = None):
    raw_fields = extract_ticket_fields(
        text,
        (
            "phone_a",
            "phone_b",
            "msisdn",
            "event_datetime",
            "event_date",
            "event_time",
            "region",
            "submitted_at",
        ),
    )
    phone_a_raw = raw_fields["phone_a"]
    phone_b_raw = raw_fields["phone_b"]
    msisdn_raw = raw_fields["msisdn"]
    datetime_raw = raw_fields["event_datetime"]
    date_raw = raw_fields["event_date"]
    time_raw = raw_fields["event_time"]
    region = raw_fields["region"]
    submitted_raw = raw_fields["submitted_at"]
    submitted_at = parse_datetime_value(submitted_raw) if submitted_raw else None

    phone_a_values = extract_phone_values(phone_a_raw, allow_short=True)
    phone_b_values = extract_phone_values(phone_b_raw, allow_short=True)
    partial_phone_a = extract_partial_phone(phone_a_raw)
    if partial_phone_a and not phone_a_values:
        phone_a_values = [partial_phone_a]

    event_date = parse_date_value(date_raw) or parse_date_value(datetime_raw)
    event_clock = parse_time_value(time_raw)
    event_time_range = parse_event_time_range(datetime_raw)
    event_datetimes = parse_event_datetimes(datetime_raw)
    embedded_datetime_raw = " ".join(value for value in (phone_a_raw, phone_b_raw) if value)
    if not event_date and not event_datetimes:
        event_date = parse_date_value(embedded_datetime_raw)
        event_datetimes = parse_event_datetimes(embedded_datetime_raw)

    general_problem = bool(
        datetime_raw
        and (DATE_RANGE_PATTERN.search(datetime_raw) or GENERAL_PROBLEM_PATTERN.search(datetime_raw))
    )
    event_date_source = "explicit" if event_date else None
    if general_problem:
        reference = submitted_at or now or datetime.now()
        event_date = reference.date() - timedelta(days=1)
        event_date_source = "fallback_yesterday"

    time_only = parse_time_value(datetime_raw)
    submitted_local = None
    if submitted_at:
        submitted_msk = submitted_at.replace(tzinfo=ZoneInfo("Europe/Moscow"))
        submitted_local = submitted_msk.astimezone(ZoneInfo(resolve_timezone(region)))

    if not event_date and time_only and submitted_local and time_only <= submitted_local.time():
        event_date = submitted_local.date()
        event_datetimes = [datetime.combine(event_date, time_only)]
        event_date_source = "ticket_submitted_at"
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
        "msisdn": normalize_phone(msisdn_raw),
        "phone_a": phone_a_values[0] if phone_a_values else normalize_phone(phone_a_raw),
        "phone_b": phone_b_values[0] if phone_b_values else normalize_phone(phone_b_raw),
    }

    return {
        "phone_a": normalized_phones["phone_a"],
        "phone_a_values": phone_a_values,
        "phone_a_partial": bool(partial_phone_a),
        "phone_a_raw": phone_a_raw,
        "phone_b": normalized_phones["phone_b"],
        "phone_b_values": phone_b_values,
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
        "submitted_at": submitted_at,
        "problem_scope": "general" if general_problem else None,
        "event_date_source": event_date_source,
        "region": region,
    }
