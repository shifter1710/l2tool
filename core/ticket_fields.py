import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class TicketField:
    title: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class TicketFieldMatch:
    value: str
    line_number: int
    line_text: str


_LINE_START = r"^[^\S\r\n]*"


TICKET_FIELDS: dict[str, TicketField] = {
    "phone_a": TicketField(
        title="Номер А",
        patterns=(
            _LINE_START + r"Номер звонящего\s*\(А\)\s*[:：]\s*(.+)",
            _LINE_START + r"Номер звонящего\s*[:：]\s*(.+)",
            _LINE_START + r"Номер А\s*[:：]\s*(.+)",
        ),
    ),
    "phone_b": TicketField(
        title="Номер Б",
        patterns=(
            _LINE_START + r"Номер принимающего звонок\s*\(Б\)\s*[:：]\s*(.+)",
            _LINE_START + r"Номер принимающего звонок\s*Б\s*[:：]\s*(.+)",
            _LINE_START + r"Номер принимающего\s*[:：]\s*(.+)",
            _LINE_START + r"Номер Б\s*[:：]\s*(.+)",
            _LINE_START + r"Б\s*[:：]\s*(.+)",
            _LINE_START + r"callee\s*[:：]\s*(.+)",
            _LINE_START + r"number_b\s*[:：]\s*(.+)",
        ),
    ),
    "msisdn": TicketField(
        title="Номер клиента",
        patterns=(
            _LINE_START + r"Номер клиента\s*\(msisdn\)\s*[:：]\s*(.+)",
            _LINE_START + r"msisdn\s*[:：]\s*(.+)",
            _LINE_START + r"Номер клиента\s*[:：]\s*(.+)",
        ),
    ),
    "event_datetime": TicketField(
        title="Дата и время проблемного звонка",
        patterns=(
            _LINE_START + r"Дата и время проблемного звонка\s*[:：]\s*(.+)",
            _LINE_START + r"Дата и время звонка\s*[:：]\s*(.+)",
            _LINE_START + r"Время события\s*[:：]\s*(.+)",
        ),
    ),
    "event_date": TicketField(
        title="Дата",
        patterns=(
            _LINE_START + r"Дата проблемного звонка\s*[:：]\s*(.+)",
            _LINE_START + r"Дата звонка\s*[:：]\s*(.+)",
            _LINE_START + r"Дата события\s*[:：]\s*(.+)",
            _LINE_START + r"Дата\s*[:：]\s*(.+)",
        ),
    ),
    "event_time": TicketField(
        title="Время",
        patterns=(
            _LINE_START + r"Время проблемного звонка\s*[:：]\s*(.+)",
            _LINE_START + r"Время звонка\s*[:：]\s*(.+)",
            _LINE_START + r"Время\s*[:：]\s*(.+)",
        ),
    ),
    "region": TicketField(
        title="Местонахождение",
        patterns=(
            _LINE_START + r"Местонахождение абонента\s*[:：]\s*(.+)",
            _LINE_START + r"Местонахождение\s*[:：]\s*(.+)",
            _LINE_START + r"Регион\s*[:：]\s*(.+)",
        ),
    ),
    "submitted_at": TicketField(
        title="Дата отправки",
        patterns=(
            _LINE_START + r"Дата отправки\s*[:：]\s*(.+)",
            _LINE_START + r"Дата создания ЕИ\s*[:：]\s*(.+)",
            _LINE_START + r"Дата создания\s*[:：]\s*(.+)",
        ),
    ),
}


def find_ticket_field(text: str, field_name: str) -> TicketFieldMatch | None:
    field = TICKET_FIELDS[field_name]

    for pattern in field.patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if not match:
            continue

        line_number = text.count("\n", 0, match.start()) + 1
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        if line_end == -1:
            line_end = len(text)
        return TicketFieldMatch(
            value=match.group(1).strip(),
            line_number=line_number,
            line_text=text[line_start:line_end].rstrip("\r"),
        )

    return None


def extract_ticket_fields(
    text: str,
    field_names: Iterable[str],
) -> dict[str, str | None]:
    values = {}
    for field_name in field_names:
        match = find_ticket_field(text, field_name)
        values[field_name] = match.value if match else None
    return values
