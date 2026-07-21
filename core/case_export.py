import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def iso_value(value, timezone_name: str | None = None):
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo(timezone_name or "Europe/Moscow"))
        return value.isoformat()

    if isinstance(value, date):
        return value.isoformat()

    return value


def build_case_dict(
    ctx: dict,
    selected_modules: list[str],
    links_by_module: dict[str, list[str]],
    *,
    product: str | None,
    file_name: str | None,
):
    timezone_name = ctx.get("tz") or "Europe/Moscow"

    return {
        "schema_version": 1,
        "case_type": "unknown",
        "product": product,
        "identifiers": {
            "msisdn": ctx.get("msisdn"),
            "phone_a": ctx.get("phone_a"),
            "phone_a_values": list(ctx.get("phone_a_values") or []),
            "phone_b": ctx.get("phone_b"),
            "phone_b_values": list(ctx.get("phone_b_values") or []),
            "call_uuid": "",
        },
        "event": {
            "timezone": timezone_name,
            "date": iso_value(ctx.get("event_date"), timezone_name),
            "time": iso_value(ctx.get("event_time"), timezone_name),
            "datetimes": [
                iso_value(value, timezone_name)
                for value in ctx.get("event_datetimes", [])
            ],
            "time_range": [
                iso_value(value, timezone_name)
                for value in (ctx.get("event_time_range") or [])
            ],
            "window_minutes": ctx.get("window"),
        },
        "interpretation": {
            "problem_scope": ctx.get("problem_scope"),
            "event_date_source": ctx.get("event_date_source"),
            "phone_a_partial": bool(ctx.get("phone_a_partial")),
        },
        "location": {
            "region": ctx.get("region"),
        },
        "search": {
            "selected_modules": list(selected_modules),
            "links_by_module": {
                module_name: list(links)
                for module_name, links in links_by_module.items()
            },
        },
        "source": {
            "tool": "l2tool",
            "file_name": file_name,
            "submitted_at_msk": iso_value(ctx.get("submitted_at"), "Europe/Moscow"),
        },
    }


def write_case_json(path: str | Path, case_data: dict):
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(case_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def parsed_sidecar_path(input_path: str | Path):
    input_path = Path(input_path)
    return input_path.with_name(f"{input_path.stem}.parsed.json")
