#!/usr/bin/env python3

import argparse
from dataclasses import dataclass, field
from pathlib import Path

from core import parser
from core.parser import is_empty_phone_value
from core.timezones import resolve_timezone
from core.utils import hash_phone

import modules.attached_call_myconnect as attached_call_myconnect
import modules.bff_logs_opensearch as bff_logs_opensearch
import modules.find_call_in_logs as find_call_in_logs
import modules.profile_not_found_myconnect as profile_not_found_myconnect

DEFAULT_FILE = "tickets/current.txt"
DEFAULT_OPEN = "zapis,bff,myconnect,myconnect_call"
DEFAULT_WINDOW = 120

MODULES = {
    "zapis": find_call_in_logs,
    "bff": bff_logs_opensearch,
    "myconnect": profile_not_found_myconnect,
    "myconnect_call": attached_call_myconnect,
}

ALIASES = {
    "grafana": "zapis",
    "find_call_in_logs": "zapis",
    "logs": "bff",
    "bff_logs_opensearch": "bff",
    "profile_not_found_myconnect": "myconnect",
    "attached": "myconnect_call",
    "attached_call_myconnect": "myconnect_call",
}


@dataclass
class RunResult:
    ctx: dict
    selected_modules: list[str]
    links_by_module: dict[str, list[str]]
    lines: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def read_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def resolve_modules(open_arg: str):
    selected = list(MODULES.keys()) if open_arg == "all" else open_arg.split(",")
    resolved = []

    for raw_name in selected:
        raw_name = raw_name.strip()
        if not raw_name:
            continue

        name = ALIASES.get(raw_name, raw_name)
        if name not in MODULES:
            print(f"[WARN] Unknown module: {raw_name}")
            continue

        resolved.append(name)

    return resolved


def format_phone_normalization(ctx):
    labels = {
        "msisdn": "Номер клиента",
        "phone_a": "Номер А",
        "phone_b": "Номер Б",
        "caller": "caller",
        "callee": "callee",
    }

    phone_fields = ctx.get("phone_fields", {})
    normalized_phones = ctx.get("normalized_phones", {})
    lines = []

    for field_name, raw_value in phone_fields.items():
        if not raw_value:
            continue

        label = labels.get(field_name, field_name)
        normalized_value = normalized_phones.get(field_name)

        if normalized_value:
            lines.append(f"{label} нормализован: {raw_value} -> {normalized_value}")
        elif is_empty_phone_value(raw_value):
            lines.append(f"{label} не задан: {raw_value}")
        else:
            lines.append(f"Не удалось нормализовать номер {label}: {raw_value}")

    return lines


def print_phone_normalization(ctx):
    for line in format_phone_normalization(ctx):
        print(line)


def format_event_time(ctx):
    event_count = len(ctx.get("event_datetimes", []))
    lines = []

    if event_count:
        lines.append(f"События звонков найдены: {event_count}")

    if len(ctx.get("event_datetimes", [])) > 1:
        lines.append("Найдено несколько времен события:")
        for event_datetime in ctx["event_datetimes"]:
            lines.append(f"- {event_datetime:%Y-%m-%d %H:%M:%S}")
    elif ctx.get("event_time"):
        lines.append(f"Найдено время события: {ctx['event_time']:%Y-%m-%d %H:%M:%S}")
    else:
        lines.append("Дата/время не найдены — выполняю поиск без привязки ко времени")

    return lines


def print_event_time(ctx):
    for line in format_event_time(ctx):
        print(line)


def format_opensearch_periods(selected_modules):
    periods = []

    for name in selected_modules:
        period = getattr(MODULES[name], "SEARCH_PERIOD", None)
        if period and period not in periods:
            periods.append(period)

    lines = []
    for date_from, date_to in periods:
        lines.append(f"OpenSearch: период поиска с {date_from} по {date_to}")

    return lines


def print_opensearch_periods(selected_modules):
    for line in format_opensearch_periods(selected_modules):
        print(line)


def format_parsed_context(ctx):
    lines = ["--- Parsed context ---"]

    for k, v in ctx.items():
        if k in ("phone_fields", "normalized_phones"):
            continue
        lines.append(f"{k}: {v}")

    lines.extend(format_event_time(ctx))
    lines.extend(format_opensearch_periods(ctx.get("selected_modules", [])))
    lines.extend(format_phone_normalization(ctx))

    if ctx.get("msisdn_raw") and not ctx.get("msisdn"):
        lines.append("Поиск по msisdn пропущен")

    if ctx.get("msisdn"):
        lines.append(f"msisdn_hash: {hash_phone(ctx['msisdn'])}")

    lines.append("----------------------")
    return lines


def run_ticket(
    text,
    open_arg=DEFAULT_OPEN,
    window=DEFAULT_WINDOW,
):
    ctx = parser.parse(text)
    ctx["tz"] = resolve_timezone(ctx.get("region"))
    ctx["window"] = window
    selected = resolve_modules(open_arg)
    ctx["selected_modules"] = selected

    lines = format_parsed_context(ctx)
    lines.append("")

    links_by_module = {}
    errors = []

    for name in selected:
        mod = MODULES[name]

        try:
            links = mod.build(ctx)
        except Exception as e:
            message = f"[ERROR] Module failed: {name}: {e}"
            errors.append(message)
            lines.append(message)
            continue

        if links:
            links_by_module[name] = links

    if not links_by_module:
        lines.append("No URLs generated")
        return RunResult(ctx, selected, links_by_module, lines, errors)

    for name, links in links_by_module.items():
        lines.append(f"[{name}]")
        for url in links:
            lines.append(url)

    return RunResult(ctx, selected, links_by_module, lines, errors)


def main():
    ap = argparse.ArgumentParser(description="L2 ticket helper")
    ap.add_argument("--file", default=DEFAULT_FILE, help="Path to ticket text file")
    ap.add_argument(
        "--open",
        default=DEFAULT_OPEN,
        help="Modules: zapis,bff,myconnect,myconnect_call or all",
    )
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW, help="Window in minutes for Grafana")

    args = ap.parse_args()

    try:
        text = read_file(args.file)
    except FileNotFoundError:
        ap.error(f"ticket file not found: {args.file}")

    result = run_ticket(
        text,
        open_arg=args.open,
        window=args.window,
    )
    print("\n" + "\n".join(result.lines))


if __name__ == "__main__":
    main()
