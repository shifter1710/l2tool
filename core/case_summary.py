"""Сводка кейса и форматтеры полей для блока «Распознанные данные»."""


from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.products import product_title
from core.utils import hash_phone


def format_value(value):
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    return str(value) if value not in (None, "") else "—"


def event_value(ctx):
    if ctx.get("event_time_range"):
        start, end = ctx["event_time_range"]
        return f"{format_value(start)} — {format_value(end)}"
    if ctx.get("event_datetimes"):
        return ", ".join(format_value(value) for value in ctx["event_datetimes"])
    return format_value(ctx.get("event_time") or ctx.get("event_date"))


def phone_values(ctx, field_name):
    values = ctx.get(f"{field_name}_values") or []
    return [value for value in values if value] or [ctx.get(field_name)]


def utc_offset_label(ctx):
    timezone_name = ctx.get("tz")
    if not timezone_name:
        return None

    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return None

    reference = ctx.get("event_time")
    if not reference and ctx.get("event_datetimes"):
        reference = ctx["event_datetimes"][0]
    if not reference and ctx.get("event_time_range"):
        reference = ctx["event_time_range"][0]
    if not reference and ctx.get("event_date"):
        reference = datetime.combine(ctx["event_date"], datetime.min.time())
    if not reference:
        reference = datetime.now(timezone)

    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone)
    else:
        reference = reference.astimezone(timezone)

    offset = reference.utcoffset()
    if offset is None:
        return None

    total_minutes = int(offset.total_seconds() / 60)
    sign = "+" if total_minutes >= 0 else "−"
    absolute_minutes = abs(total_minutes)
    hours, minutes = divmod(absolute_minutes, 60)
    if minutes:
        return f"{sign}{hours}:{minutes:02d}"
    return f"{sign}{hours}"


def phone_with_hash(value):
    """Номер с хешем для поиска в логах: «79157771575 · f4156ce0dd60d4e5»."""
    text = format_value(value)
    if text == "—":
        return text
    try:
        return f"{text} · {hash_phone(value)}"
    except (TypeError, ValueError):
        return text


def _summary_product_title(product):
    try:
        return product_title(product)
    except ValueError:
        return str(product)


def case_summary_fields(ctx, product=None):
    """Поля сводки кейса «Ключ: значение»; пустые значения в список не попадают.

    Источники — только реально существующие поля контекста разбора:
    msisdn / phone_a_values / phone_b_values (с hash_phone), время события,
    регион с UTC-смещением, submitted_at, call_uuid, окно и продукт формы.
    """
    fields = []

    msisdn = ctx.get("msisdn")
    if msisdn:
        fields.append(("Номер клиента", phone_with_hash(msisdn)))

    numbers_a = [value for value in phone_values(ctx, "phone_a") if value]
    if numbers_a:
        value = ", ".join(phone_with_hash(number) for number in numbers_a)
        if ctx.get("phone_a_partial"):
            value += " — распознан частично"
        fields.append(("Номер А", value))

    numbers_b = [value for value in phone_values(ctx, "phone_b") if value]
    if numbers_b:
        fields.append(("Номер Б", ", ".join(phone_with_hash(number) for number in numbers_b)))

    event = event_value(ctx)
    if event != "—":
        fields.append(("Дата и время", event))

    offset = utc_offset_label(ctx)
    region = ctx.get("region")
    if region:
        fields.append(("Регион", f"{region} (UTC{offset})" if offset else str(region)))
    elif ctx.get("tz"):
        timezone_name = str(ctx["tz"])
        fields.append(
            ("Часовой пояс", f"{timezone_name} (UTC{offset})" if offset else timezone_name)
        )

    submitted = format_value(ctx.get("submitted_at"))
    if submitted != "—":
        fields.append(("Дата создания заявки", submitted))

    if ctx.get("call_uuid"):
        fields.append(("UUID звонка", str(ctx["call_uuid"])))

    window = ctx.get("window")
    if window not in (None, ""):
        fields.append(("Окно поиска", f"{window} мин"))

    if product:
        fields.append(("Продукт", _summary_product_title(product)))

    if ctx.get("problem_scope") == "general":
        fields.append(("Общая проблема", "да"))

    return fields
