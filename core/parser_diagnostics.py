import json
import re
from pathlib import Path

from core.parser import is_empty_phone_value, parse_date_value, parse_datetime_value, parse_time_value

PHONE_FIELDS = (
    ("msisdn", "msisdn_raw", "Номер клиента", [r"^\s*Номер клиента\s*\(msisdn\)\s*[:：]\s*(.+)", r"^\s*msisdn\s*[:：]\s*(.+)", r"^\s*Номер клиента\s*[:：]\s*(.+)"]),
    ("phone_a", "phone_a_raw", "Номер А", [r"^\s*Номер звонящего\s*\(А\)\s*[:：]\s*(.+)", r"^\s*Номер звонящего\s*[:：]\s*(.+)", r"^\s*Номер А\s*[:：]\s*(.+)"]),
    ("phone_b", "phone_b_raw", "Номер Б", [r"^\s*Номер принимающего звонок\s*\(Б\)\s*[:：]\s*(.+)", r"^\s*Номер принимающего звонок\s*Б\s*[:：]\s*(.+)", r"^\s*Номер принимающего\s*[:：]\s*(.+)", r"^\s*Номер Б\s*[:：]\s*(.+)", r"^\s*Б\s*[:：]\s*(.+)", r"^\s*callee\s*[:：]\s*(.+)", r"^\s*number_b\s*[:：]\s*(.+)"]),
)

DATETIME_FIELDS = (
    (
        "event_datetime",
        "datetime_parse_failed",
        "Дата и время проблемного звонка",
        [r"^\s*Дата и время проблемного звонка\s*[:：]\s*(.+)", r"^\s*Дата и время звонка\s*[:：]\s*(.+)", r"^\s*Время события\s*[:：]\s*(.+)"],
        parse_datetime_value,
    ),
    (
        "event_date",
        "date_parse_failed",
        "Дата",
        [r"^\s*Дата проблемного звонка\s*[:：]\s*(.+)", r"^\s*Дата звонка\s*[:：]\s*(.+)", r"^\s*Дата события\s*[:：]\s*(.+)", r"^\s*Дата\s*[:：]\s*(.+)"],
        parse_date_value,
    ),
    (
        "event_time",
        "time_parse_failed",
        "Время",
        [r"^\s*Время проблемного звонка\s*[:：]\s*(.+)", r"^\s*Время звонка\s*[:：]\s*(.+)", r"^\s*Время\s*[:：]\s*(.+)"],
        parse_time_value,
    ),
)


def _issue(field, reason, line_number, line_text, message):
    return {
        "field": field,
        "reason": reason,
        "line_number": line_number,
        "line_text": line_text,
        "message": message,
    }


def _find_field_line(text, patterns):
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                return match.group(1).strip(), line_number, line

    return None, 0, ""


def collect_parse_issues(text, ctx) -> list[dict]:
    issues = []

    for field, raw_key, title, patterns in PHONE_FIELDS:
        raw_value = ctx.get(raw_key)
        if not raw_value or is_empty_phone_value(raw_value):
            continue

        if ctx.get(field) is None:
            _, line_number, line_text = _find_field_line(text, patterns)
            issues.append(
                _issue(
                    field=field,
                    reason="phone_normalization_failed",
                    line_number=line_number,
                    line_text=line_text,
                    message=f"{title} не распознан: {raw_value}",
                )
            )

    for field, reason, title, patterns, parser_fn in DATETIME_FIELDS:
        raw_value, line_number, line_text = _find_field_line(text, patterns)
        if not raw_value or is_empty_phone_value(raw_value):
            continue

        if parser_fn(raw_value) is None:
            issues.append(
                _issue(
                    field=field,
                    reason=reason,
                    line_number=line_number,
                    line_text=line_text,
                    message=f"{title} не распознано: {raw_value}",
                )
            )

    return issues


def write_parse_issues(issues, path="parser_issues/parser_issues.jsonl"):
    if not issues:
        return

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as file:
        for issue in issues:
            file.write(json.dumps(issue, ensure_ascii=False, sort_keys=True))
            file.write("\n")
