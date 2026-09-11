"""Разбор истории звонков, вытянутой из истории баланса.

Внешний скрипт детализации умеет два формата, и оба здесь разбираются в
список звонков.

Сводный формат (текущий): запись — строка с датой и диапазоном времени
«ДД.ММ.ГГГГ чч:мм:сс-чч:мм:сс (ч:мм:сс)» и строка участников «А → Б»
(А — звонящий) либо «А → Б ← В (условие)» — звонок на номер Б, ушедший по
переадресации на В. Направления относительно абонента в строках нет, поэтому
номер абонента передаётся с msisdn, а без него определяется как самый
частый участник выгрузки.

Событийный формат (прежний): строка с датой и временем (МСК) и заголовком
события, затем строка с направлением, номером и длительностью и
необязательная строка типа звонка. Цепочка переадресации из трёх событий
(исходящий на бесплатный сервисный номер, сама переадресация и входящая
нога звонящего) схлопывается в один звонок.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from core.config import config_value

MSK_TIMEZONE = "Europe/Moscow"
DIGITAL_CALL_TYPE = "Цифровой звонок"
VOLTE_CALL_TYPE = "Интернет-звонки: VoLTE"
FORWARD_MERGE_SECONDS = 5

TIMESTAMP_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(?P<title>\S.*)$"
)
FORWARD_PATTERN = re.compile(
    r"^Переадресация по условию\s+(?P<condition>.+?)\s*(?:→|->)\s*(?P<phone>\d{3,})\s*$"
)
DETAIL_PATTERN = re.compile(
    r"^\s*(?P<arrow>→|->|←|<-)\s*(?P<phone>\S+)\s+Duration:\s*(?P<duration>\d+)\s*SECOND\s*$",
    re.IGNORECASE,
)
NAMED_INCOMING_PATTERN = re.compile(
    r"^Входящая связь:\s*(?P<name>.+?)\s*\((?P<code>\d+)\)\s*$"
)
OUTGOING_TITLE_PATTERN = re.compile(r"^Связь\.\s*Исходящая")
INCOMING_TITLE_PATTERN = re.compile(r"^Связь\.\s*Входящая")
APP_CALL_TITLE_PATTERN = re.compile(r"^Безлимитный звонок")
CATEGORY_PATTERN = re.compile(r"\((?P<category>[^()]*)\)\s*$")
RANGE_HEADER_PATTERN = re.compile(
    r"^\s*(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})\s+"
    r"(?P<start>\d{2}:\d{2}:\d{2})-(?P<end>\d{2}:\d{2}:\d{2})\s+"
    r"\((?P<duration>\d+:\d{2}:\d{2})\)\s*$"
)
RANGE_PARTICIPANTS_PATTERN = re.compile(
    r"^\s*(?P<caller>\+?\d+)\s*→\s*(?P<callee>\+?\d+)"
    r"(?:\s*←\s*(?P<forwarded_to>\+?\d+))?"
    r"(?:\s*\((?P<condition>[^()]+)\))?\s*$"
)

CALL_TYPE_LABELS = {
    DIGITAL_CALL_TYPE: "цифровой (MyConnect)",
    VOLTE_CALL_TYPE: "VoLTE",
}


def normalize_remote_phone(value):
    """Нормальный номер — 7XXXXXXXXXX; короткие коды (0900) проходят как есть."""
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 10:
        return "7" + digits
    if len(digits) == 11 and digits[0] in "78":
        return "7" + digits[1:]
    return str(value).strip()


def _secretary_numbers_from_config():
    try:
        raw = config_value("call_history.secretary_numbers", [])
    except (OSError, ValueError):
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [normalize_remote_phone(item) for item in raw if str(item).strip()]


def secretary_numbers_ordered():
    """Номера Секретаря: настройки сайта приоритетнее config.toml.

    Секция call_history в diagnostic_sources.json действует, как только
    номера сохранены на странице настроек (даже пустой список); пока её
    нет, читается [call_history] из config.toml.
    """
    from core.dynamic_sources import load_call_history

    try:
        section = load_call_history()
    except (OSError, ValueError):
        section = {}
    if "secretary_numbers" in section:
        raw = section.get("secretary_numbers")
        items = raw if isinstance(raw, list) else []
        return list(
            dict.fromkeys(
                normalize_remote_phone(item) for item in items if str(item).strip()
            )
        )
    return list(dict.fromkeys(_secretary_numbers_from_config()))


def secretary_numbers():
    """Настроенные номера Секретаря (для сопоставления при разборе звонков)."""
    return set(secretary_numbers_ordered())


@dataclass
class RawEvent:
    """Одно событие истории: нога звонка или строка переадресации."""

    started_at: datetime
    title: str
    kind: str | None = None  # out · in · in_named · out_app · forward
    phone: str | None = None
    duration: int | None = None
    call_type: str | None = None
    category: str | None = None
    remote_name: str | None = None
    arrow: str | None = None


@dataclass
class HistoryCall:
    """Звонок после группировки: переадресационные ноги слиты в одно событие."""

    started_at: datetime
    direction: str  # in · out
    remote_phone: str | None = None
    remote_name: str | None = None
    duration: int | None = None
    call_type: str | None = None
    forward_condition: str | None = None
    service_phone: str | None = None
    via_app: bool = False
    secretary: bool = False
    service_leg: bool = False
    legs: int = 1

    @property
    def digital(self):
        return self.call_type == DIGITAL_CALL_TYPE

    @property
    def forwarded(self):
        return bool(self.forward_condition)


def _event_kind(title):
    if OUTGOING_TITLE_PATTERN.match(title):
        return "out"
    if INCOMING_TITLE_PATTERN.match(title):
        return "in"
    if NAMED_INCOMING_PATTERN.match(title):
        return "in_named"
    if APP_CALL_TITLE_PATTERN.match(title):
        return "out_app"
    return None


def _finalize_event(event):
    if event is None:
        return None
    kind = _event_kind(event.title)
    if kind == "in_named":
        match = NAMED_INCOMING_PATTERN.match(event.title)
        event.remote_name = match.group("name")

    # Стрелка определяет направление надёжнее заголовка.
    arrow_out = event.arrow in {"→", "->"}
    arrow_in = event.arrow in {"←", "<-"}
    if kind is None:
        kind = "out" if arrow_out else "in" if arrow_in else None
    elif arrow_out and kind in {"in", "in_named"}:
        kind, event.remote_name = "out", None
    elif arrow_in and kind in {"out", "out_app"}:
        kind = "in"
    event.kind = kind

    category = CATEGORY_PATTERN.search(event.title)
    if category:
        event.category = category.group("category").strip()
    if event.phone:
        event.phone = normalize_remote_phone(event.phone)
    return event


def _parse_events(text):
    events = []
    pending = None

    def flush():
        nonlocal pending
        finalized = _finalize_event(pending)
        if finalized is not None:
            events.append(finalized)
        pending = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            flush()
            continue

        timestamp_match = TIMESTAMP_PATTERN.match(line)
        if timestamp_match:
            flush()
            started_at = datetime.strptime(timestamp_match.group("timestamp"), "%Y-%m-%d %H:%M:%S")
            title = timestamp_match.group("title").strip()
            forward_match = FORWARD_PATTERN.match(title)
            if forward_match:
                condition = forward_match.group("condition").strip().strip("«»“”\"„'")
                events.append(
                    RawEvent(
                        started_at=started_at,
                        title=title,
                        kind="forward",
                        phone=normalize_remote_phone(forward_match.group("phone")),
                        remote_name=condition or None,
                    )
                )
            else:
                pending = RawEvent(started_at=started_at, title=title)
            continue

        detail_match = DETAIL_PATTERN.match(line)
        if detail_match and pending is not None:
            pending.arrow = detail_match.group("arrow")
            pending.phone = detail_match.group("phone")
            pending.duration = int(detail_match.group("duration"))
            continue

        # Строка типа звонка («Цифровой звонок», «Интернет-звонки: VoLTE») —
        # с отступом, после строки с номером; заметки без отступа игнорируем.
        if pending is not None and pending.phone and pending.call_type is None:
            if line != line.lstrip():
                pending.call_type = line.strip()

    flush()
    return events


@dataclass
class _RangeRecord:
    """Запись сводного формата: один звонок целиком, включая переадресацию."""

    started_at: datetime
    duration: int
    caller: str
    callee: str
    forwarded_to: str | None = None
    condition: str | None = None


def _parse_duration(text):
    hours, minutes, seconds = (int(part) for part in text.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def _parse_range_records(text):
    records = []
    pending = None

    for raw_line in text.splitlines():
        header = RANGE_HEADER_PATTERN.match(raw_line)
        if header:
            year, month, day = (
                int(header.group("year")),
                int(header.group("month")),
                int(header.group("day")),
            )
            hour, minute, second = (
                int(part) for part in header.group("start").split(":")
            )
            pending = (
                datetime(year, month, day, hour, minute, second),
                _parse_duration(header.group("duration")),
            )
            continue

        participants = RANGE_PARTICIPANTS_PATTERN.match(raw_line)
        if participants and pending is not None:
            forwarded_to = participants.group("forwarded_to")
            records.append(
                _RangeRecord(
                    started_at=pending[0],
                    duration=pending[1],
                    caller=normalize_remote_phone(participants.group("caller")),
                    callee=normalize_remote_phone(participants.group("callee")),
                    forwarded_to=(
                        normalize_remote_phone(forwarded_to) if forwarded_to else None
                    ),
                    condition=participants.group("condition"),
                )
            )
            pending = None

    return records


def _range_subscriber(records, msisdn):
    """Номер абонента, чья выгрузка: msisdn, а без него — самый частый участник."""
    if msisdn:
        return normalize_remote_phone(msisdn)
    counts = {}
    for record in records:
        for phone in (record.caller, record.callee, record.forwarded_to):
            if phone:
                counts[phone] = counts.get(phone, 0) + 1
    if not counts:
        return None
    # Абонент участвует в каждой записи, поэтому максимум частоты — он;
    # при равенстве (короткая выгрузка) побеждает встреченный раньше.
    return max(counts, key=counts.get)


def _range_call(record, subscriber):
    if record.forwarded_to:
        call = HistoryCall(
            started_at=record.started_at,
            direction="in",
            remote_phone=record.caller,
            duration=record.duration,
            forward_condition=record.condition,
            service_phone=record.callee,
            legs=3,
        )
        call.secretary = _secretary_involved(call.remote_phone, call.service_phone)
        return call

    if record.caller == subscriber:
        direction, remote = "out", record.callee
    elif record.callee == subscriber:
        direction, remote = "in", record.caller
    else:
        direction, remote = "in", record.caller
    call = HistoryCall(
        started_at=record.started_at,
        direction=direction,
        remote_phone=remote,
        duration=record.duration,
    )
    call.secretary = _secretary_involved(call.remote_phone)
    return call


def _near(first, second):
    return abs((first.started_at - second.started_at).total_seconds()) <= FORWARD_MERGE_SECONDS


def _secretary_involved(*phones):
    configured = secretary_numbers()
    return any(phone in configured for phone in phones if phone)


def _single_call(event):
    direction = "out" if event.kind in {"out", "out_app"} else "in"
    call = HistoryCall(
        started_at=event.started_at,
        direction=direction,
        remote_phone=event.phone,
        remote_name=event.remote_name,
        duration=event.duration,
        call_type=event.call_type,
        via_app=event.kind == "out_app",
    )
    call.service_leg = bool(event.category) and "сервисный" in event.category.lower()
    call.secretary = _secretary_involved(call.remote_phone)
    return call


def _forwarded_call(forward, legs):
    caller_leg = next(
        (leg for leg in legs if leg.kind in {"in", "in_named"} and leg is not forward),
        None,
    )
    service_leg = next(
        (leg for leg in legs if leg.kind in {"out", "out_app"} and leg is not forward),
        None,
    )
    source = caller_leg or service_leg or forward
    call = HistoryCall(
        started_at=forward.started_at,
        direction="in",
        remote_phone=(caller_leg.phone if caller_leg else None) or forward.phone,
        remote_name=caller_leg.remote_name if caller_leg else None,
        duration=source.duration,
        call_type=source.call_type,
        forward_condition=forward.remote_name,
        service_phone=forward.phone,
        legs=len(legs),
    )
    call.secretary = _secretary_involved(call.remote_phone, call.service_phone)
    return call


def _group_calls(events):
    calls = []
    merged = set()

    def try_merge(indices, predicate):
        for index in indices:
            if 0 <= index < len(events) and index not in merged and predicate(events[index]):
                merged.add(index)
                return events[index]
        return None

    def to_service_leg(leg):
        return leg.kind in {"out", "out_app"} and leg.phone == event.phone

    def is_caller_leg(leg):
        return leg.kind in {"in", "in_named"}

    for index, event in enumerate(events):
        if event.kind != "forward" or index in merged:
            continue

        merged.add(index)

        # Ноги переадресации лежат рядом по времени: сервисная нога может
        # стоять и до, и после строки переадресации.
        service_leg = try_merge([index - 1], to_service_leg)
        caller_leg = None
        following = index + 1
        while following < len(events):
            candidate = events[following]
            if candidate.kind == "forward" or not _near(candidate, event):
                break
            if caller_leg is None:
                caller_leg = try_merge([following], is_caller_leg)
            if service_leg is None:
                service_leg = try_merge([following], to_service_leg)
            if caller_leg and service_leg:
                break
            following += 1

        legs = [leg for leg in (service_leg, event, caller_leg) if leg is not None]
        calls.append(_forwarded_call(event, legs))

    calls.extend(
        _single_call(event)
        for index, event in enumerate(events)
        if index not in merged and event.kind in {"out", "out_app", "in", "in_named"}
    )

    calls.sort(key=lambda call: call.started_at)
    return calls


def parse_call_history(text, msisdn=None):
    """Текст истории звонков из баланса → список сгруппированных звонков.

    Форматы распознаются оба сразу: сводный использует msisdn (или выводит
    абонента по частоте), событийный разбирается по стрелкам как раньше.
    """
    records = _parse_range_records(text)
    calls = []
    if records:
        subscriber = _range_subscriber(records, msisdn)
        calls = [_range_call(record, subscriber) for record in records]
    calls.extend(_group_calls(_parse_events(text)))
    calls.sort(key=lambda call: call.started_at)
    return calls


def call_title(call):
    arrow = "→" if call.direction == "out" else "←"
    direction = "исходящий" if call.direction == "out" else "входящий"
    phone = call.remote_phone or "номер не распознан"
    if call.remote_name:
        phone = f"{phone} ({call.remote_name})"
    return f"{direction} {arrow} {phone}"


def call_badges(call):
    badges = []
    if call.duration is not None:
        badges.append(f"{call.duration} с")
    if call.call_type:
        badges.append(CALL_TYPE_LABELS.get(call.call_type, call.call_type))
    if call.forwarded:
        badges.append(f"переадресация «{call.forward_condition}» → {call.service_phone}")
    if call.via_app:
        badges.append("через Мой МТС")
    if call.secretary:
        badges.append("Секретарь")
    if call.service_leg:
        badges.append("сервисный номер")
    return badges


def call_label(call):
    parts = [f"{call.started_at:%d.%m.%Y %H:%M:%S}", call_title(call), *call_badges(call)]
    return " · ".join(parts)


def call_context(call, msisdn=None, window=60):
    """Контекст одного звонка, совместимый с модулями и динамическими блоками."""
    remote = call.remote_phone
    if msisdn and call.direction == "out":
        phone_a, phone_b = msisdn, remote
    elif msisdn:
        phone_a, phone_b = remote, msisdn
    else:
        phone_a, phone_b = remote, None

    return {
        "msisdn": msisdn,
        "msisdn_values": [msisdn] if msisdn else [],
        "phone_a": phone_a,
        "phone_a_values": [phone_a] if phone_a else [],
        "phone_b": phone_b,
        "phone_b_values": [phone_b] if phone_b else [],
        "event_date": call.started_at.date(),
        "event_time": call.started_at,
        "event_datetimes": [call.started_at],
        "event_time_range": None,
        "region": None,
        "tz": MSK_TIMEZONE,
        "window": window,
    }
