import json
import os
from pathlib import Path

from core.parser import (
    is_empty_phone_value,
    parse_date_value,
    parse_datetime_value,
    parse_time_value,
)
from core.ticket_fields import TICKET_FIELDS, find_ticket_field

PHONE_FIELDS = (
    ("msisdn", "msisdn_raw"),
    ("phone_a", "phone_a_raw"),
    ("phone_b", "phone_b_raw"),
)

DATETIME_FIELDS = (
    (
        "event_datetime",
        "datetime_parse_failed",
        parse_datetime_value,
    ),
    (
        "event_date",
        "date_parse_failed",
        parse_date_value,
    ),
    (
        "event_time",
        "time_parse_failed",
        parse_time_value,
    ),
)
SKIPPED_EVENT_VALUES = {"пропустить"}


def _issue(field, reason, line_number, line_text, message):
    return {
        "field": field,
        "reason": reason,
        "line_number": line_number,
        "line_text": line_text,
        "message": message,
    }


def collect_parse_issues(text, ctx, require_time=True) -> list[dict]:
    issues = []
    event_was_skipped = False

    for field, raw_key in PHONE_FIELDS:
        raw_value = ctx.get(raw_key)
        if not raw_value or is_empty_phone_value(raw_value):
            continue

        if ctx.get(field) is None:
            match = find_ticket_field(text, field)
            issues.append(
                _issue(
                    field=field,
                    reason="phone_normalization_failed",
                    line_number=match.line_number if match else 0,
                    line_text=match.line_text if match else "",
                    message=f"{TICKET_FIELDS[field].title} не распознан: {raw_value}",
                )
            )

    for field, reason, parser_fn in DATETIME_FIELDS:
        match = find_ticket_field(text, field)
        if match and match.value.strip().lower() in SKIPPED_EVENT_VALUES:
            event_was_skipped = True
        if not match or is_empty_phone_value(match.value):
            continue

        parsed_value = parser_fn(match.value)
        if field == "event_datetime":
            parsed_value = ctx.get("event_time") or ctx.get("event_date")

        if parsed_value is None:
            issues.append(
                _issue(
                    field=field,
                    reason=reason,
                    line_number=match.line_number,
                    line_text=match.line_text,
                    message=(
                        f"{TICKET_FIELDS[field].title} не распознано: {match.value}"
                    ),
                )
            )

    has_event_time = any(
        (
            ctx.get("event_date"),
            ctx.get("event_time"),
            ctx.get("event_time_range"),
            ctx.get("event_datetimes"),
        )
    )
    has_event_issue = any(
        issue["field"] in {"event_datetime", "event_date", "event_time"}
        for issue in issues
    )
    if require_time and not has_event_time and not has_event_issue and not event_was_skipped:
        match = find_ticket_field(text, "event_datetime")
        issues.append(
            _issue(
                field="event_datetime",
                reason="event_time_missing",
                line_number=match.line_number if match else 0,
                line_text=match.line_text if match else "",
                message="Дата и время звонка не найдены",
            )
        )

    return issues


def write_parse_issues(issues, path="parser_issues/parser_issues.jsonl"):
    if not issues:
        return

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    file_descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o600,
    )
    os.fchmod(file_descriptor, 0o600)
    with os.fdopen(file_descriptor, "a", encoding="utf-8") as file:
        for issue in issues:
            file.write(json.dumps(issue, ensure_ascii=False, sort_keys=True))
            file.write("\n")
