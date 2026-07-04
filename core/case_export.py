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
            "phone_b": ctx.get("phone_b"),
        },
        "event": {
            "timezone": timezone_name,
            "date": iso_value(ctx.get("event_date"), timezone_name),
            "time": iso_value(ctx.get("event_time"), timezone_name),
            "datetimes": [
                iso_value(value, timezone_name)
                for value in ctx.get("event_datetimes", [])
            ],
            "window_minutes": ctx.get("window"),
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
