"""Ядро диагностики заявки: каталог сервисов, разбор, сборка ссылок.

Общий слой для точек входа приложения: превращает текст заявки в контекст,
строит диагностические ссылки и собирает текстовое представление результата.
"""

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from core import call_history, history, parser
from core.config import optional_value
from core.dynamic_sources import build_source_links, load_store
from core.parser import is_empty_phone_value
from core.parser_diagnostics import collect_parse_issues, write_parse_issues
from core.products import available_products
from core.timezones import resolve_timezone
from core.utils import hash_phone, normalize_uuid
from services.opensearch import configured_search_period
from services.registry import service_modules, service_titles

DEFAULT_FILE = "tickets/current.txt"
DEFAULT_OPEN = "zapis,bff,myconnect,myconnect_call"
DEFAULT_WINDOW = 60
LOKI_RETENTION_DAYS = 5
CALL_HISTORY_DEFAULT_OPEN = "zapis"
CALL_HISTORY_MAX_CALLS = 50

MODULES = service_modules()
MODULE_TITLES = service_titles()


def configured_call_history_open():
    value = optional_value("call_history.default_open", CALL_HISTORY_DEFAULT_OPEN)
    return str(value).strip() or CALL_HISTORY_DEFAULT_OPEN


def configured_default_window():
    try:
        value = int(optional_value("defaults.window", DEFAULT_WINDOW))
    except (TypeError, ValueError):
        return DEFAULT_WINDOW
    return value if 0 <= value <= 1440 else DEFAULT_WINDOW


def configured_call_history_max_calls():
    try:
        value = int(optional_value("call_history.max_calls", CALL_HISTORY_MAX_CALLS))
    except (TypeError, ValueError):
        return CALL_HISTORY_MAX_CALLS
    return value if 1 <= value <= 500 else CALL_HISTORY_MAX_CALLS


def _configured_product(key, fallback):
    value = str(optional_value(key, fallback) or "").strip()
    return value if value in available_products() else fallback


def configured_default_product():
    """Продукт основной формы: defaults.product в config.toml."""
    return _configured_product("defaults.product", "recording")


def configured_calls_product():
    """Продукт панели истории звонков: defaults.calls_product в config.toml."""
    return _configured_product("defaults.calls_product", "calls")


@dataclass
class RunResult:
    ctx: dict
    selected_modules: list[str]
    links_by_module: dict[str, list[str]]
    lines: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    status: str = "success"


@dataclass
class CallHistoryEntry:
    """Один звонок из истории баланса и ссылки, построенные по нему."""

    call: call_history.HistoryCall
    label: str
    links_by_module: dict[str, list[str]]
    errors: list[str] = field(default_factory=list)


@dataclass
class CallHistoryResult:
    msisdn: str | None
    entries: list[CallHistoryEntry]
    total_calls: int
    truncated: bool
    warnings: list[str] = field(default_factory=list)
    status: str = "success"


def enabled_dynamic_sources():
    """Включённые блоки из diagnostic_sources.json; пусто — файла нет или он пуст."""
    try:
        data = load_store()
    except (OSError, ValueError):
        return []
    return [source for source in data.get("sources", []) if source.get("enabled", True)]


def managed_product_keys():
    """Продукты, переведённые на динамические блоки (статика для них не используется).

    Если включённых блоков нет совсем, диагностика работает по статической схеме.
    """
    try:
        data = load_store()
    except (OSError, ValueError):
        return set()
    if not enabled_dynamic_sources():
        return set()
    return {
        entry["key"]
        for entry in data.get("products", [])
        if entry.get("managed") or not entry.get("builtin")
    }


def available_services():
    """Каталог «ключ → сервис»: динамические блоки + статические модули.

    Динамические блоки приоритетны; статические модули остаются фолбэком
    для сервисов, которых нет в динамической конфигурации.
    """
    services = {}
    for block in enabled_dynamic_sources():
        services[block["id"]] = {
            "title": block.get("name") or block["id"],
            "requires_call_uuid": block.get("level") == "uuid",
            "source": block,
        }
    for name, mod in MODULES.items():
        services.setdefault(
            name,
            {
                "title": MODULE_TITLES.get(name, name),
                "requires_call_uuid": bool(getattr(mod, "REQUIRES_CALL_UUID", False)),
                "source": None,
            },
        )
    return services


def _services_hint(services):
    items = []
    for key, service in services.items():
        if service["source"] is not None:
            items.append(f"{service['title']} ({key})")
        else:
            items.append(key)
    return ", ".join(items)


def resolve_modules(open_arg: str, call_uuid=None):
    services = available_services()
    if open_arg == "all":
        resolved = list(services)
    else:
        lookup = {}
        for key, service in services.items():
            lookup[key.lower()] = key
            lookup.setdefault(service["title"].lower(), key)

        resolved = []
        for raw_name in open_arg.split(","):
            raw_name = raw_name.strip()
            if not raw_name:
                continue

            key = lookup.get(raw_name.lower())
            if key is None:
                raise ValueError(
                    f"Unknown service: {raw_name}. Available: {_services_hint(services)}"
                )

            if key not in resolved:
                resolved.append(key)

    if open_arg == "all" and not call_uuid:
        resolved = [
            key
            for key in resolved
            if not services[key]["requires_call_uuid"]
        ]

    return resolved


def requires_call_uuid_modules():
    return [
        key
        for key, service in available_services().items()
        if service["requires_call_uuid"]
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
        mod = MODULES.get(name)
        if mod is None:
            continue
        period = getattr(mod, "SEARCH_PERIOD", None)
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

    try:
        retention_days = int(optional_value("defaults.loki_retention_days", LOKI_RETENTION_DAYS))
    except (TypeError, ValueError):
        retention_days = LOKI_RETENTION_DAYS

    tz = ZoneInfo(ctx.get("tz", "Europe/Moscow"))
    current = now or datetime.now(tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    else:
        current = current.astimezone(tz)

    if event_time:
        event_date = event_time.date()

    if event_date and (current.date() - event_date).days > retention_days:
        return [
            "[WARN] Loki хранит логи только 5 дней. "
            "По Grafana/Loki данные могут быть уже недоступны."
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


def build_links(ctx, selected_modules):
    services = available_services()
    links_by_module = {}
    errors = []

    for name in selected_modules:
        service = services.get(name)
        if service is None:
            errors.append(f"[ERROR] Unknown service: {name}")
            continue

        try:
            if service["source"] is not None:
                links = build_source_links(
                    service["source"], ctx, call_uuid=ctx.get("call_uuid")
                )
            else:
                links = MODULES[name].build(ctx)
        except Exception as e:
            errors.append(f"[ERROR] Service failed: {name}: {e}")
            continue

        if links:
            links_by_module[name] = links
        else:
            errors.append(f"[ERROR] Service generated no links: {name}")

    return links_by_module, errors


def terminal_link(label: str, url: str) -> str:
    return f"\033]8;;{url}\033\\{label}\033]8;;\033\\"


def format_links(links_by_module, titles=None):
    if titles is None:
        titles = {
            key: service["title"] for key, service in available_services().items()
        }
    lines = []

    for name, links in links_by_module.items():
        lines.append(f"[{titles.get(name, name)}]")
        lines.extend(terminal_link(url, url) for url in links)

    return lines


def run_ticket(
    text,
    open_arg=DEFAULT_OPEN,
    window=DEFAULT_WINDOW,
    input_file=DEFAULT_FILE,
    save_history=False,
    history_root=None,
    write_diagnostics=True,
    parse_text=None,
    call_uuid=None,
    require_time=True,
):
    # None → history.HISTORY_ROOT читается в момент вызова, а не импорта
    history_root = history_root or history.HISTORY_ROOT
    if call_uuid:
        call_uuid = normalize_uuid(call_uuid)

    source_text = parse_text if parse_text is not None else text
    ctx = parser.parse(source_text)
    ctx["tz"] = resolve_timezone(ctx.get("region"))
    ctx["window"] = window
    selected = resolve_modules(open_arg, call_uuid=call_uuid)
    ctx["selected_modules"] = selected
    ctx["call_uuid"] = call_uuid

    issues = collect_parse_issues(source_text, ctx, require_time=require_time)
    lines, warnings = partition_warnings(format_parsed_context(ctx))
    warnings.extend(format_loki_retention_warning(ctx))
    lines.append("")

    if issues and write_diagnostics:
        write_parse_issues(issues)

    if issues and not ctx.get("msisdn"):
        lines.extend(format_parse_errors(issues))
        return RunResult(
            ctx,
            selected,
            {},
            lines,
            [issue["message"] for issue in issues],
            status="failed",
        )
    if issues:
        # Номер клиента распознан — диагностика строится и при проблемах
        # в остальных полях («все номера в этот промежуток», неизвестное
        # время и т.п.): проблемы показываются предупреждениями.
        warnings.extend(f"[WARN] {issue['message']}" for issue in issues)

    matches = history.find_matches(ctx, history_root=history_root)
    lines.extend(history.format_matches(matches))
    lines.append("")

    links_by_module, errors = build_links(ctx, selected)
    warnings.extend(errors)

    if errors and links_by_module:
        status = "partial"
    elif errors or not links_by_module:
        status = "failed"
    else:
        status = "success"

    saved_history_path = None
    if save_history and status == "success":
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
        return RunResult(
            ctx,
            selected,
            links_by_module,
            lines,
            errors,
            status=status,
        )

    lines.extend(format_warnings(warnings))
    if warnings:
        lines.append("")
    lines.extend(format_links(links_by_module))

    if saved_history_path:
        lines.append("")
        lines.append(f"History saved: {saved_history_path.as_posix()}")

    return RunResult(
        ctx,
        selected,
        links_by_module,
        lines,
        errors,
        status=status,
    )


def normalize_client_phone(value):
    """Номер клиента для истории звонков: строго 7XXXXXXXXXX или ошибка."""
    if not value:
        return None
    normalized = call_history.normalize_remote_phone(value)
    if len(normalized) == 11 and normalized.startswith("7") and normalized.isdigit():
        return normalized
    raise ValueError(f"Номер клиента указан некорректно: {value}")


def run_call_history(
    text,
    msisdn=None,
    open_arg=None,
    window=DEFAULT_WINDOW,
    max_calls=None,
):
    """Ссылки по каждому звонку из истории, вытянутой из истории баланса."""
    open_arg = open_arg or configured_call_history_open()
    max_calls = max_calls or configured_call_history_max_calls()
    client_phone = normalize_client_phone(msisdn)

    calls = call_history.parse_call_history(text, msisdn=client_phone)
    if not calls:
        raise ValueError(
            "Не удалось распознать события звонков. Проверьте, что вставлена "
            "история звонков, вытянутая из истории баланса"
        )

    selected = resolve_modules(open_arg)
    shown = calls[:max_calls]
    truncated = len(calls) > max_calls

    warnings = []
    if not client_phone:
        warnings.append(
            "Номер клиента не указан: ссылки строятся только по номеру собеседника"
        )
    if truncated:
        warnings.append(f"Показаны первые {max_calls} звонков из {len(calls)}")
    oldest = min(call.started_at for call in shown)
    warnings.extend(
        format_loki_retention_warning(
            {"event_date": oldest.date(), "tz": call_history.MSK_TIMEZONE}
        )
    )

    entries = []
    for call in shown:
        ctx = call_history.call_context(call, client_phone, window)
        links_by_module, errors = build_links(ctx, selected)
        entries.append(
            CallHistoryEntry(
                call=call,
                label=call_history.call_label(call),
                links_by_module=links_by_module,
                errors=errors,
            )
        )

    status = "success" if any(entry.links_by_module for entry in entries) else "failed"
    return CallHistoryResult(
        msisdn=client_phone,
        entries=entries,
        total_calls=len(calls),
        truncated=truncated,
        warnings=warnings,
        status=status,
    )
