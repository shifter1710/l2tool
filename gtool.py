#!/usr/bin/env python3

import argparse
import sys
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core import history, parser
from core.case_export import build_case_dict, parsed_sidecar_path, write_case_json
from core.parser import is_empty_phone_value
from core.parser_diagnostics import collect_parse_issues, write_parse_issues
from core.products import available_products, product_title, resolve_product_modules
from core.timezones import resolve_timezone
from core.utils import hash_phone
from services.opensearch import configured_search_period
from services.registry import service_modules, service_titles

DEFAULT_FILE = "tickets/current.txt"
DEFAULT_OPEN = "zapis,bff,myconnect,myconnect_call"
DEFAULT_WINDOW = 60
LOKI_RETENTION_DAYS = 5

MODULES = service_modules()
MODULE_TITLES = service_titles()


@dataclass
class RunResult:
    ctx: dict
    selected_modules: list[str]
    links_by_module: dict[str, list[str]]
    lines: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


PARSE_FIX_FIELDS = {
    "msisdn": ("Номер клиента (msisdn)", "Номер клиента"),
    "phone_a": ("Номер звонящего (А)", "Номер А"),
    "phone_b": ("Номер принимающего звонок (Б)", "Номер Б"),
    "event_datetime": ("Дата и время проблемного звонка", "Дата и время звонка"),
    "event_date": ("Дата проблемного звонка", "Дата звонка"),
    "event_time": ("Время проблемного звонка", "Дата и время звонка"),
}
PHONE_FIX_FIELDS = {"msisdn", "phone_a", "phone_b"}
EVENT_FIX_FIELDS = {"event_datetime", "event_date", "event_time"}


def read_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def resolve_modules(open_arg: str, call_uuid=None):
    selected = list(MODULES.keys()) if open_arg == "all" else open_arg.split(",")
    resolved = []
    available = ", ".join(MODULES)

    for raw_name in selected:
        raw_name = raw_name.strip()
        if not raw_name:
            continue

        if raw_name not in MODULES:
            raise ValueError(f"Unknown service: {raw_name}. Available: {available}")

        if raw_name not in resolved:
            resolved.append(raw_name)

    if open_arg == "all" and not call_uuid:
        resolved = [
            name
            for name in resolved
            if not getattr(MODULES[name], "REQUIRES_CALL_UUID", False)
        ]

    return resolved


def requires_call_uuid_modules():
    return [
        name for name, mod in MODULES.items() if getattr(mod, "REQUIRES_CALL_UUID", False)
    ]


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
            lines.append(f"[WARN] Не удалось нормализовать номер {label}: {raw_value}")

    return lines


def format_event_time(ctx):
    event_count = len(ctx.get("event_datetimes", []))
    lines = []

    if ctx.get("problem_scope") == "general":
        lines.append(
            "[WARN] Похоже на общую проблему: поиск за предыдущий день с 08:00 до 20:00"
        )

    if ctx.get("event_time_range"):
        start, end = ctx["event_time_range"]
        lines.append(
            f"Найден диапазон времени события: {start:%Y-%m-%d %H:%M:%S} - {end:%Y-%m-%d %H:%M:%S}"
        )
        return lines

    if event_count:
        lines.append(f"События звонков найдены: {event_count}")

    if len(ctx.get("event_datetimes", [])) > 1:
        lines.append("Найдено несколько времен события:")
        lines.extend(
            f"- {event_datetime:%Y-%m-%d %H:%M:%S}"
            for event_datetime in ctx["event_datetimes"]
        )
    elif ctx.get("event_time"):
        lines.append(f"Найдено время события: {ctx['event_time']:%Y-%m-%d %H:%M:%S}")
    elif ctx.get("event_date"):
        lines.append(
            f"Найдена только дата события: {ctx['event_date']:%Y-%m-%d}, поиск с 08:00 до 20:00"
        )
    else:
        lines.append("[WARN] Дата/время не найдены — выполняю поиск без привязки ко времени")

    return lines


def format_opensearch_periods(selected_modules, ctx=None):
    periods = []

    for name in selected_modules:
        period = getattr(MODULES[name], "SEARCH_PERIOD", None)
        if period:
            period = configured_search_period(name, period, ctx)
        if period and period not in periods:
            periods.append(period)

    lines = []
    for date_from, date_to in periods:
        lines.append(f"OpenSearch: период поиска с {date_from} по {date_to}")

    return lines


def format_loki_retention_warning(ctx, now=None):
    event_date = ctx.get("event_date")
    event_time = ctx.get("event_time")

    if not event_date and not event_time:
        return []

    tz = ZoneInfo(ctx.get("tz", "Europe/Moscow"))
    current = now or datetime.now(tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    else:
        current = current.astimezone(tz)

    if event_time:
        event_date = event_time.date()

    if event_date and (current.date() - event_date).days > LOKI_RETENTION_DAYS:
        return [
            "[WARN] Loki хранит логи только 5 дней. По Grafana/Loki данные могут быть уже недоступны."
        ]

    return []


def format_parsed_context(ctx):
    lines = ["--- Parsed context ---"]

    phone_fields = ctx.get("phone_fields", {})
    number_lines = [
        ("Номер клиента", "msisdn"),
        ("Номер А", "phone_a"),
        ("Номер Б", "phone_b"),
    ]
    for label, field_name in number_lines:
        values = ctx.get(f"{field_name}_values") or []
        value = ", ".join(values) if values else ctx.get(field_name)
        value = value or phone_fields.get(field_name) or "не найден"
        lines.append(f"{label}: {value}")

    if ctx.get("phone_a_partial"):
        lines.append("[WARN] Номер А распознан частично: используется известный префикс")

    lines.extend(format_event_time(ctx))
    lines.append(f"Timezone: {ctx.get('tz')}")
    lines.append(f"Window: {ctx.get('window')}")
    lines.append(f"selected_modules: {', '.join(ctx.get('selected_modules', []))}")
    lines.extend(format_opensearch_periods(ctx.get("selected_modules", []), ctx))
    lines.extend(format_phone_normalization(ctx))

    if ctx.get("msisdn_raw") and not ctx.get("msisdn"):
        lines.append("[WARN] Поиск по msisdn пропущен")

    if ctx.get("msisdn"):
        lines.append(f"msisdn_hash: {hash_phone(ctx['msisdn'])}")

    lines.append("----------------------")
    return lines


def partition_warnings(lines):
    regular = []
    warnings = []
    for line in lines:
        if line.startswith(("[WARN]", "[ERROR]")):
            warnings.append(line)
        else:
            regular.append(line)
    return regular, warnings


def format_warnings(warnings):
    if not warnings:
        return []

    return ["--- Warnings and errors ---", *warnings, "---------------------------"]


def format_parse_errors(issues):
    lines = ["--- Parse errors ---"]
    for issue in issues:
        lines.append(f"[ERROR] {issue['message']}")
        if issue["line_number"]:
            lines.append(f"  Строка {issue['line_number']}: {issue['line_text']}")
    lines.extend(
        [
            "Исправьте указанные поля; ссылки не сформированы.",
            "--------------------",
        ]
    )
    return lines


def prompt_parse_fixes(text, issues, input_fn=None):
    input_fn = input if input_fn is None else input_fn
    corrections = []
    prompted_fields = set()

    for issue in issues:
        field_name = issue["field"]
        if field_name in prompted_fields or field_name not in PARSE_FIX_FIELDS:
            continue

        source_label, prompt_label = PARSE_FIX_FIELDS[field_name]
        if field_name in PHONE_FIX_FIELDS:
            suffix = " (Enter — оставить пустым)"
        elif field_name in EVENT_FIX_FIELDS:
            suffix = " (Enter — пропустить)"
        else:
            suffix = ""
        value = input_fn(f"Введите {prompt_label}{suffix}: ").strip()
        if value:
            corrections.append(f"{source_label}: {value}")
        elif field_name in PHONE_FIX_FIELDS:
            corrections.append(f"{source_label}: нет")
        elif field_name in EVENT_FIX_FIELDS:
            corrections.append(f"{source_label}: пропустить")
        prompted_fields.add(field_name)

    return "\n".join([*corrections, text])


def is_date_only_context(ctx):
    return bool(
        ctx.get("event_date")
        and not ctx.get("event_time")
        and not ctx.get("event_time_range")
        and not ctx.get("event_datetimes")
    )


def prompt_date_only_window(text, ctx, input_fn=None):
    input_fn = input if input_fn is None else input_fn
    event_datetime = input_fn(
        "Найдена только дата. Нажмите Enter для поиска с 08:00 до 20:00 "
        "или введите дату и время звонка (ДД.ММ.ГГГГ ЧЧ:ММ): "
    ).strip()
    if not event_datetime:
        return text

    return "\n".join(
        [
            f"Дата и время проблемного звонка: {event_datetime}",
            text,
        ]
    )


def build_links(ctx, selected_modules):
    links_by_module = {}
    errors = []

    for name in selected_modules:
        mod = MODULES[name]

        try:
            links = mod.build(ctx)
        except Exception as e:
            errors.append(f"[ERROR] Service failed: {name}: {e}")
            continue

        if links:
            links_by_module[name] = links

    return links_by_module, errors


def terminal_link(label: str, url: str) -> str:
    return f"\033]8;;{url}\033\\{label}\033]8;;\033\\"


def format_links(links_by_module):
    lines = []

    for name, links in links_by_module.items():
        lines.append(f"[{MODULE_TITLES.get(name, name)}]")
        lines.extend(terminal_link(url, url) for url in links)

    return lines


def open_links(links_by_module):
    for links in links_by_module.values():
        for link in links:
            webbrowser.open(link)


def prompt_product():
    products = available_products()
    print("Выберите продукт:")
    for index, product_key in enumerate(products, start=1):
        print(f"{index}. {product_title(product_key)}")

    try:
        choice = int(input("Введите номер: ").strip())
    except ValueError as error:
        raise ValueError("Некорректный номер продукта") from error

    if not 1 <= choice <= len(products):
        raise ValueError("Некорректный номер продукта")

    return products[choice - 1]


def prompt_recording_scenario(call_uuid=None, input_fn=None):
    input_fn = input if input_fn is None else input_fn
    print("Выберите сценарий записи:")
    print("1. Не зашёл в петлю")
    print("2. Не обработалась запись")
    print("3. Обработалась, но нет в приложении (пока не настроено)")
    choice = input_fn("Введите номер: ").strip()
    if choice not in {"1", "2"}:
        if choice == "3":
            print("Этот сценарий пока не настроен")
            return None, call_uuid
        raise ValueError("Некорректный номер сценария записи")

    if not call_uuid:
        call_uuid = input_fn("Введите UUID записи: ").strip()

    if choice == "1":
        return "recording_mgw", call_uuid
    return "recording_mgw,recording_vss_crs,recording_crs,recording_collector", call_uuid


def product_open_arg(product_key):
    modules = resolve_product_modules(product_key)
    if not modules:
        print(f"Для продукта {product_title(product_key)} пока нет настроенных сервисов")
        return None

    return ",".join(modules)


def run_ticket(
    text,
    open_arg=DEFAULT_OPEN,
    window=DEFAULT_WINDOW,
    input_file=DEFAULT_FILE,
    save_history=False,
    history_root=history.HISTORY_ROOT,
    write_diagnostics=True,
    parse_text=None,
    call_uuid=None,
):
    source_text = parse_text if parse_text is not None else text
    ctx = parser.parse(source_text)
    ctx["tz"] = resolve_timezone(ctx.get("region"))
    ctx["window"] = window
    selected = resolve_modules(open_arg, call_uuid=call_uuid)
    ctx["selected_modules"] = selected
    ctx["call_uuid"] = call_uuid

    issues = collect_parse_issues(source_text, ctx)
    lines, warnings = partition_warnings(format_parsed_context(ctx))
    warnings.extend(format_loki_retention_warning(ctx))
    lines.append("")

    if issues and write_diagnostics:
        write_parse_issues(issues)

    if issues:
        lines.extend(format_parse_errors(issues))
        return RunResult(ctx, selected, {}, lines, [issue["message"] for issue in issues])

    matches = history.find_matches(ctx, history_root=history_root)
    lines.extend(history.format_matches(matches))
    lines.append("")

    links_by_module, errors = build_links(ctx, selected)
    warnings.extend(errors)

    saved_history_path = None
    if save_history:
        saved_history_path = history.save_ticket_history(
            ctx=ctx,
            input_file=input_file,
            raw_ticket=text,
            links_by_module=links_by_module,
            history_root=history_root,
        )

    if not links_by_module:
        lines.extend(format_warnings(warnings))
        if warnings:
            lines.append("")
        lines.append("No URLs generated")
        if saved_history_path:
            lines.append(f"History saved: {saved_history_path.as_posix()}")
        return RunResult(ctx, selected, links_by_module, lines, errors)

    lines.extend(format_warnings(warnings))
    if warnings:
        lines.append("")
    lines.extend(format_links(links_by_module))

    if saved_history_path:
        lines.append("")
        lines.append(f"History saved: {saved_history_path.as_posix()}")

    return RunResult(ctx, selected, links_by_module, lines, errors)


def main():
    ap = argparse.ArgumentParser(description="L2 ticket helper")
    ap.add_argument("--file", default=DEFAULT_FILE, help="Path to ticket text file")
    ap.add_argument(
        "--open",
        default=None,
        help="Services: zapis,sip_stack,bff,myconnect,myconnect_call or all",
    )
    ap.add_argument("--product", choices=available_products(), help="Product profile")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW, help="Window in minutes for Grafana")
    ap.add_argument("--export-case", help="Path to write parsed case JSON")
    ap.add_argument("--call-uuid", help="UUID записи для сценариев записи")
    ap.add_argument("--no-history", action="store_true", help="Do not save a history archive")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse, match history and print links without saving history or diagnostics",
    )

    args = ap.parse_args()

    if args.product and args.open:
        ap.error("Use either --product or --open, not both")
    if args.window < 0:
        ap.error("--window must be non-negative")

    product_key = args.product
    interactive = sys.stdin.isatty()
    call_uuid = args.call_uuid

    if not product_key and not args.open and interactive:
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

        if product_key == "recording" and interactive:
            try:
                scenario_arg, call_uuid = prompt_recording_scenario(call_uuid)
            except ValueError as error:
                print(str(error))
                return
            if scenario_arg is None:
                return
            open_arg = scenario_arg

    try:
        text = read_file(args.file)
    except FileNotFoundError:
        ap.error(f"ticket file not found: {args.file}")

    try:
        preview_selected = resolve_modules(open_arg, call_uuid=call_uuid)
    except ValueError as error:
        ap.error(str(error))

    if args.open == "all" and not call_uuid:
        skipped = requires_call_uuid_modules()
        if skipped:
            print(
                "Сервисы записи пропущены "
                f"({', '.join(skipped)}): передайте --call-uuid, чтобы включить их"
            )

    preview_ctx = parser.parse(text)
    preview_ctx["tz"] = resolve_timezone(preview_ctx.get("region"))
    preview_ctx["window"] = args.window
    preview_ctx["selected_modules"] = preview_selected
    preview_issues = collect_parse_issues(text, preview_ctx)
    parse_text = text

    if preview_issues and interactive:
        print("\n" + "\n".join(format_parsed_context(preview_ctx)))
        print("\n" + "\n".join(format_parse_errors(preview_issues)))
        parse_text = prompt_parse_fixes(text, preview_issues)

    date_only_ctx = parser.parse(parse_text)
    if interactive and is_date_only_context(date_only_ctx):
        parse_text = prompt_date_only_window(parse_text, date_only_ctx)

    try:
        result = run_ticket(
            text,
            open_arg=open_arg,
            window=args.window,
            input_file=args.file,
            save_history=not args.no_history and not args.dry_run,
            write_diagnostics=not args.dry_run,
            parse_text=parse_text,
            call_uuid=call_uuid,
        )
    except ValueError as error:
        ap.error(str(error))

    print("\n" + "\n".join(result.lines))

    case_data = build_case_dict(
        result.ctx,
        result.selected_modules,
        result.links_by_module,
        product=product_key,
        file_name=Path(args.file).name,
    )

    if not args.dry_run:
        sidecar_path = write_case_json(parsed_sidecar_path(args.file), case_data)
        print(f"Parsed case saved to: {sidecar_path}")

    if args.export_case:
        output_path = write_case_json(args.export_case, case_data)
        print(f"Case JSON saved to: {output_path}")

if __name__ == "__main__":
    main()
