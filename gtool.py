#!/usr/bin/env python3

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from core import parser
from core.parser import is_empty_phone_value
from core.products import available_products, product_title, resolve_product_modules
from core.timezones import resolve_timezone
from core.utils import hash_phone

import modules.attached_call_myconnect as attached_call_myconnect
import modules.bff_logs_opensearch as bff_logs_opensearch
import modules.find_call_in_logs as find_call_in_logs
import modules.profile_not_found_myconnect as profile_not_found_myconnect
import modules.sip_stack_opensearch as sip_stack_opensearch

DEFAULT_FILE = "tickets/current.txt"
DEFAULT_OPEN = "zapis,bff,myconnect,myconnect_call"
DEFAULT_WINDOW = 120

MODULES = {
    "zapis": find_call_in_logs,
    "sip_stack": sip_stack_opensearch,
    "bff": bff_logs_opensearch,
    "myconnect": profile_not_found_myconnect,
    "myconnect_call": attached_call_myconnect,
}

MODULE_TITLES = {
    "zapis": "Grafana / find-call-in-logs",
    "sip_stack": "SIP stack / OpenSearch",
    "bff": "BFF / OpenSearch",
    "myconnect": "MyConnect / OpenSearch",
    "myconnect_call": "MyConnect call / OpenSearch",
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
    available = ", ".join(MODULES)

    for raw_name in selected:
        raw_name = raw_name.strip()
        if not raw_name:
            continue

        if raw_name not in MODULES:
            raise ValueError(f"Unknown module: {raw_name}. Available: {available}")

        resolved.append(raw_name)

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


def format_parsed_context(ctx):
    lines = ["--- Parsed context ---"]

    phone_fields = ctx.get("phone_fields", {})
    number_lines = [
        ("Номер клиента", "msisdn"),
        ("Номер А", "phone_a"),
        ("Номер Б", "phone_b"),
    ]
    for label, field_name in number_lines:
        value = ctx.get(field_name) or phone_fields.get(field_name) or "не найден"
        lines.append(f"{label}: {value}")

    lines.extend(format_event_time(ctx))
    lines.append(f"Timezone: {ctx.get('tz')}")
    lines.append(f"Window: {ctx.get('window')}")
    lines.append(f"selected_modules: {', '.join(ctx.get('selected_modules', []))}")
    lines.extend(format_opensearch_periods(ctx.get("selected_modules", [])))
    lines.extend(format_phone_normalization(ctx))

    if ctx.get("msisdn_raw") and not ctx.get("msisdn"):
        lines.append("Поиск по msisdn пропущен")

    if ctx.get("msisdn"):
        lines.append(f"msisdn_hash: {hash_phone(ctx['msisdn'])}")

    lines.append("----------------------")
    return lines


def build_links(ctx, selected_modules):
    links_by_module = {}
    errors = []

    for name in selected_modules:
        mod = MODULES[name]

        try:
            links = mod.build(ctx)
        except Exception as e:
            errors.append(f"[ERROR] Module failed: {name}: {e}")
            continue

        if links:
            links_by_module[name] = links

    return links_by_module, errors


def format_links(links_by_module):
    lines = []

    for name, links in links_by_module.items():
        lines.append(f"[{name}]")
        lines.extend(links)

    return lines


def prompt_product():
    products = available_products()
    print("Выберите продукт:")
    for index, product_key in enumerate(products, start=1):
        print(f"{index}. {product_title(product_key)}")

    try:
        choice = int(input("Введите номер: ").strip())
    except ValueError:
        raise ValueError("Некорректный номер продукта")

    if not 1 <= choice <= len(products):
        raise ValueError("Некорректный номер продукта")

    return products[choice - 1]


def product_open_arg(product_key):
    modules = resolve_product_modules(product_key)
    if not modules:
        print(f"Для продукта {product_title(product_key)} пока нет настроенных модулей")
        return None

    return ",".join(modules)


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
    links_by_module, errors = build_links(ctx, selected)
    lines.extend(errors)

    if not links_by_module:
        lines.append("No URLs generated")
        return RunResult(ctx, selected, links_by_module, lines, errors)

    lines.extend(format_links(links_by_module))

    return RunResult(ctx, selected, links_by_module, lines, errors)


def main():
    ap = argparse.ArgumentParser(description="L2 ticket helper")
    ap.add_argument("--file", default=DEFAULT_FILE, help="Path to ticket text file")
    ap.add_argument(
        "--open",
        default=None,
        help="Modules: zapis,sip_stack,bff,myconnect,myconnect_call or all",
    )
    ap.add_argument("--product", choices=available_products(), help="Product profile")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW, help="Window in minutes for Grafana")

    args = ap.parse_args()

    if args.product and args.open:
        ap.error("Use either --product or --open, not both")

    product_key = args.product
    if not product_key and not args.open and sys.stdin.isatty():
        try:
            product_key = prompt_product()
        except ValueError as error:
            print(str(error))
            return

    open_arg = args.open or DEFAULT_OPEN
    if product_key:
        open_arg = product_open_arg(product_key)
        if open_arg is None:
            return

    try:
        text = read_file(args.file)
    except FileNotFoundError:
        ap.error(f"ticket file not found: {args.file}")

    try:
        result = run_ticket(
            text,
            open_arg=open_arg,
            window=args.window,
        )
    except ValueError as error:
        ap.error(str(error))

    print("\n" + "\n".join(result.lines))


if __name__ == "__main__":
    main()
