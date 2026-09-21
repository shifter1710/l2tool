"""Ядро диагностики заявки: каталог сервисов, разбор, сборка ссылок.

Общий слой для точек входа приложения: превращает текст заявки в контекст,
строит диагностические ссылки и собирает текстовое представление результата.
"""

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from core import call_history, parser
from core.config import optional_value
from core.dynamic_sources import build_source_links, load_store
from core.parser import is_empty_phone_value
from core.parser_diagnostics import collect_parse_issues
from core.products import available_products
from core.timezones import resolve_timezone
from core.utils import normalize_uuid
from services.registry import service_modules, service_titles

DEFAULT_OPEN = "zapis,bff,myconnect,myconnect_call"
DEFAULT_WINDOW = 60
LOKI_RETENTION_DAYS = 5
CALL_HISTORY_MAX_CALLS = 50

MODULES = service_modules()
MODULE_TITLES = service_titles()


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
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    status: str = "success"


@dataclass
class CallHistoryEntry:
    """Один звонок из истории баланса и ссылки, построенные по нему."""

    call: call_history.HistoryCall
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


def resolve_modules(open_arg: str, call_uuid=None, services=None):
    """Разрешить имена сервисов в ключи; services — каталог available_services().

    Каталог можно передать снаружи, чтобы одно чтение хранилища блоков
    переиспользовалось для всех звонков истории.
    """
    if services is None:
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


def _has_event_time(ctx):
    return bool(
        ctx.get("event_time")
        or ctx.get("event_datetimes")
        or ctx.get("event_time_range")
        or ctx.get("event_date")
    )


def _parsed_context_warnings(ctx):
    """Предупреждения разбора заявки — в порядке прежнего текстового вывода."""
    warnings = []

    if ctx.get("phone_a_partial"):
        warnings.append("Номер А распознан частично: используется известный префикс")

    if ctx.get("problem_scope") == "general":
        warnings.append(
            "Похоже на общую проблему: поиск за предыдущий день с 08:00 до 20:00"
        )

    if not _has_event_time(ctx):
        warnings.append("Дата/время не найдены — выполняю поиск без привязки ко времени")

    phone_fields = ctx.get("phone_fields", {})
    normalized_phones = ctx.get("normalized_phones", {})
    for field_name, label in (
        ("msisdn", "Номер клиента"),
        ("phone_a", "Номер А"),
        ("phone_b", "Номер Б"),
    ):
        raw_value = phone_fields.get(field_name)
        if not raw_value or normalized_phones.get(field_name):
            continue
        if not is_empty_phone_value(raw_value):
            warnings.append(f"Не удалось нормализовать номер {label}: {raw_value}")

    if ctx.get("msisdn_raw") and not ctx.get("msisdn"):
        warnings.append("Поиск по msisdn пропущен")

    return warnings


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


def build_links(ctx, selected_modules, services=None):
    """Собрать ссылки выбранных сервисов; services переиспользуется между звонками."""
    if services is None:
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


def run_ticket(
    text,
    open_arg=DEFAULT_OPEN,
    window=DEFAULT_WINDOW,
    parse_text=None,
    call_uuid=None,
    require_time=True,
):
    if call_uuid:
        call_uuid = normalize_uuid(call_uuid)

    source_text = parse_text if parse_text is not None else text
    ctx = parser.parse(source_text)
    ctx["tz"] = resolve_timezone(ctx.get("region"))
    ctx["window"] = window
    services = available_services()
    selected = resolve_modules(open_arg, call_uuid=call_uuid, services=services)
    ctx["selected_modules"] = selected
    ctx["call_uuid"] = call_uuid

    issues = collect_parse_issues(source_text, ctx, require_time=require_time)
    warnings = _parsed_context_warnings(ctx)
    warnings.extend(
        message.removeprefix("[WARN] ")
        for message in format_loki_retention_warning(ctx)
    )

    if issues and not ctx.get("msisdn"):
        # Без номера клиента проблемы разбора блокируют построение ссылок;
        # предупреждения разбора при этом не показываются.
        return RunResult(
            ctx,
            selected,
            {},
            [],
            [issue["message"] for issue in issues],
            status="failed",
        )
    if issues:
        # Номер клиента распознан — диагностика строится и при проблемах
        # в остальных полях («все номера в этот промежуток», неизвестное
        # время и т.п.): проблемы показываются предупреждениями.
        warnings.extend(issue["message"] for issue in issues)

    links_by_module, errors = build_links(ctx, selected, services=services)

    if errors and links_by_module:
        status = "partial"
    elif errors or not links_by_module:
        status = "failed"
    else:
        status = "success"

    return RunResult(
        ctx,
        selected,
        links_by_module,
        warnings,
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
    open_arg,
    msisdn=None,
    window=DEFAULT_WINDOW,
    max_calls=None,
):
    """Ссылки по каждому звонку из истории, вытянутой из истории баланса."""
    max_calls = max_calls or configured_call_history_max_calls()
    client_phone = normalize_client_phone(msisdn)

    calls = call_history.parse_call_history(text, msisdn=client_phone)
    if not calls:
        raise ValueError(
            "Не удалось распознать события звонков. Проверьте, что вставлена "
            "история звонков, вытянутая из истории баланса"
        )

    services = available_services()
    selected = resolve_modules(open_arg, services=services)
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
        links_by_module, errors = build_links(ctx, selected, services=services)
        entries.append(
            CallHistoryEntry(
                call=call,
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
