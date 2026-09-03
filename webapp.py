#!/usr/bin/env python3

import argparse
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import webbrowser
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask
from starlette.datastructures import UploadFile
from starlette.middleware.trustedhost import TrustedHostMiddleware

from core import history
from core.dynamic_sources import (
    LEVELS,
    build_product_links,
    delete_source,
    import_sources,
    is_managed,
    list_sources,
    load_store,
    product_groups,
    save_source,
)
from core.lost_calls_table import TableFormatError, process_table
from core.products import available_products, product_title, resolve_product_modules
from core.utils import normalize_uuid
from gtool import MODULE_TITLES, RunResult, run_ticket
from services.registry import SERVICES

ROOT_DIR = Path(__file__).resolve().parent
LOCAL_HOSTS = ["127.0.0.1", "localhost"]
MAX_TICKET_LENGTH = 200_000
MAX_UPLOAD_SIZE = 25 * 1024 * 1024
MAX_CONFIG_UPLOAD_SIZE = 2 * 1024 * 1024
ALLOWED_TABLE_SUFFIXES = {".xlsx", ".xlsm", ".csv", ".tsv"}
SECONDARY_MODULES = {
    "mgw": ["recording_mgw"],
    "pipeline": [
        "recording_mgw",
        "recording_vss_crs",
        "recording_crs",
        "recording_collector",
    ],
}
CORRECTION_FIELDS = (
    ("msisdn", "Номер клиента (msisdn)"),
    ("phone_a", "Номер звонящего (А)"),
    ("phone_b", "Номер принимающего звонок (Б)"),
    ("event_datetime", "Дата и время проблемного звонка"),
    ("region", "Местонахождение абонента"),
)

app = FastAPI(
    title="l2tool",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.state.csrf_token = secrets.token_urlsafe(32)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)
app.mount("/static", StaticFiles(directory=ROOT_DIR / "static"), name="static")
templates = Jinja2Templates(directory=ROOT_DIR / "templates")


@app.middleware("http")
async def secure_local_responses(request: Request, call_next):
    response = None
    if request.method == "POST":
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_UPLOAD_SIZE + 1024 * 1024:
                    response = PlainTextResponse(
                        "Запрос превышает 26 МБ",
                        status_code=413,
                    )
            except ValueError:
                response = PlainTextResponse(
                    "Некорректный размер запроса",
                    status_code=400,
                )
    if response is None:
        response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


def product_options():
    options = []
    for key in available_products():
        try:
            managed = is_managed(key)
        except ValueError:
            managed = False
        options.append(
            {
                "key": key,
                "title": product_title(key),
                "enabled": managed or bool(resolve_product_modules(key)),
            }
        )
    return options


def page_context(request: Request, **values):
    context = {
        "request": request,
        "csrf_token": app.state.csrf_token,
        "products": product_options(),
        "form": {
            "product": "recording",
            "window": 60,
            "ticket_text": "",
            "save_history": False,
            "corrections": {},
            "dynamic_product": False,
        },
        "result": None,
        "secondary_result": None,
        "has_uuid_level": False,
        "error": None,
        "partial": False,
    }
    context.update(values)
    return context


def form_text(form, name, default=""):
    value = form.get(name)
    return value.strip() if isinstance(value, str) else default


def validate_csrf(form):
    submitted = form_text(form, "csrf_token")
    if not submitted or not secrets.compare_digest(submitted, app.state.csrf_token):
        raise HTTPException(status_code=403, detail="Недействительная форма. Обновите страницу.")


def parse_window(form):
    raw_window = form_text(form, "window", "60")
    try:
        window = int(raw_window)
    except ValueError as error:
        raise ValueError("Окно поиска должно быть целым числом минут") from error
    if not 0 <= window <= 1440:
        raise ValueError("Окно поиска должно быть от 0 до 1440 минут")
    return window


def validate_product(product):
    if product not in available_products():
        raise ValueError("Неизвестный продукт")
    if is_managed(product):
        return []
    modules = resolve_product_modules(product)
    if not modules:
        raise ValueError(f"Для продукта «{product_title(product)}» пока нет настроенных сервисов")
    return modules


def has_uuid_sources(product):
    try:
        return is_managed(product) and bool(list_sources(product=product, level="uuid"))
    except ValueError:
        return False


def run_dynamic_ticket(
    text,
    product,
    level,
    window,
    *,
    parse_text=None,
    call_uuid=None,
    save_history=False,
    input_file="web",
):
    if level == "uuid":
        call_uuid = normalize_uuid(call_uuid)
    parsed = run_ticket(
        text,
        open_arg="",
        window=window,
        input_file=input_file,
        save_history=False,
        write_diagnostics=False,
        parse_text=parse_text,
    )
    if parsed.errors:
        return parsed

    parsed.ctx["call_uuid"] = call_uuid
    links, titles, errors = build_product_links(
        product,
        level,
        parsed.ctx,
        call_uuid=call_uuid,
    )
    parsed.ctx["service_titles"] = titles
    if not links and not errors:
        errors = [f"Для уровня «{LEVELS[level]}» ещё не добавлены диагностические блоки"]
    status = "partial" if links and errors else "failed" if errors or not links else "success"
    if save_history and status == "success":
        history.save_ticket_history(
            ctx=parsed.ctx,
            input_file=input_file,
            raw_ticket=text,
            links_by_module=links,
        )
    return RunResult(
        parsed.ctx,
        list(links),
        links,
        parsed.lines,
        errors,
        status,
    )


def build_corrected_text(ticket_text, corrections):
    correction_lines = [
        f"{label}: {corrections[field_name]}"
        for field_name, label in CORRECTION_FIELDS
        if corrections.get(field_name)
    ]
    return "\n".join([*correction_lines, ticket_text])


def normalize_datetime_picker(value):
    try:
        selected = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Выберите корректные дату и время в календаре") from error
    if selected.tzinfo is not None:
        raise ValueError("Дата и время из календаря должны быть локальными")
    return selected.strftime("%d.%m.%Y %H:%M")


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


def parsed_fields(ctx):
    msisdn = ctx.get("msisdn")
    phone_a_values = phone_values(ctx, "phone_a")
    phone_b_values = phone_values(ctx, "phone_b")

    client_side = None
    if msisdn and msisdn in phone_a_values:
        client_side = "phone_a"
    elif msisdn and msisdn in phone_b_values:
        client_side = "phone_b"

    fields = [
        {
            "label": "Номер А",
            "value": ", ".join(value for value in phone_a_values if value) or "—",
            "is_client": client_side == "phone_a",
        },
        {
            "label": "Номер Б",
            "value": ", ".join(value for value in phone_b_values if value) or "—",
            "is_client": client_side == "phone_b",
        },
    ]
    if msisdn and not client_side:
        fields.insert(
            0,
            {
                "label": "Номер клиента",
                "value": format_value(msisdn),
                "is_client": True,
                "unmatched": True,
            },
        )

    fields.extend(
        [
            {"label": "Дата и время", "value": event_value(ctx)},
            {
                "label": "Регион",
                "value": format_value(ctx.get("region")),
                "utc_offset": utc_offset_label(ctx),
            },
        ]
    )
    return fields


HISTORY_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")


def service_platforms():
    platforms = {name: definition.platform for name, definition in SERVICES.items()}
    try:
        platforms.update(
            {source["id"]: source["platform"] for source in list_sources()}
        )
    except (OSError, ValueError):
        pass
    return platforms


def history_view(matches):
    items = []
    for number, paths in matches.items():
        entries = []
        for path in paths:
            name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
            prefix = HISTORY_DATE_PREFIX.match(name)
            entries.append(
                {"date": prefix.group(0) if prefix else "", "path": str(path)}
            )
        items.append({"number": str(number), "entries": entries})
    return items


def result_view(result: RunResult, title):
    warnings = []
    for line in result.lines:
        if line.startswith(("[WARN]", "[ERROR]")):
            message = line.split("]", 1)[-1].strip()
            if message and message not in warnings:
                warnings.append(message)
    for message in result.errors:
        if message and message not in warnings:
            warnings.append(message)

    ctx = result.ctx
    platforms = service_platforms()
    return {
        "title": title,
        "status": result.status,
        "status_title": {
            "success": "Готово",
            "partial": "Частичный результат",
            "failed": "Нужна проверка",
        }.get(result.status, result.status),
        "fields": parsed_fields(ctx),
        "services": [
            {
                "key": module_name,
                "title": ctx.get("service_titles", {}).get(
                    module_name, MODULE_TITLES.get(module_name, module_name)
                ),
                "platform": platforms.get(module_name),
                "links": links,
            }
            for module_name, links in result.links_by_module.items()
        ],
        "warnings": warnings,
        "history": history_view(history.find_matches(ctx)),
    }


def render_index(request, *, status_code=200, partial=False, **values):
    return templates.TemplateResponse(
        request=request,
        name="_results.html" if partial else "index.html",
        context=page_context(request, partial=partial, **values),
        status_code=status_code,
    )


def wants_fragment(request: Request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def render_settings(request, *, status_code=200, overrides=None, **values):
    try:
        products = product_groups(overrides=overrides)
    except (OSError, ValueError) as error:
        products = []
        values.setdefault(
            "error",
            f"{error}. Проверьте файл diagnostic_sources.json или удалите его.",
        )
        status_code = max(status_code, 400)
    context = {
        "request": request,
        "csrf_token": app.state.csrf_token,
        "products": products,
        "product_options": [
            {"key": key, "title": product_title(key)} for key in available_products()
        ],
        "levels": LEVELS,
        "draft": None,
        "error": None,
        "message": None,
    }
    context.update(values)
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context=context,
        status_code=status_code,
    )


@app.get("/")
async def index(request: Request):
    return render_index(request)


@app.get("/settings")
async def settings(request: Request):
    message = None
    if request.query_params.get("saved"):
        message = "Диагностический блок сохранён и уже используется"
    elif request.query_params.get("deleted"):
        message = "Диагностический блок удалён"
    elif request.query_params.get("imported") is not None:
        added = request.query_params.get("imported", "0")
        skipped = request.query_params.get("skipped", "0")
        message = f"Импортировано блоков: {added}. Уже существовало: {skipped}"
    return render_settings(request, message=message)


@app.post("/settings/import")
async def settings_import(request: Request):
    form_data = await request.form()
    validate_csrf(form_data)
    upload = form_data.get("config_file")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return render_settings(request, error="Выберите JSON-файл конфигурации", status_code=400)

    try:
        if Path(upload.filename).suffix.lower() != ".json":
            raise ValueError("Поддерживается файл diagnostic_sources.json")
        content = await upload.read(MAX_CONFIG_UPLOAD_SIZE + 1)
        if len(content) > MAX_CONFIG_UPLOAD_SIZE:
            raise ValueError("Файл конфигурации превышает 2 МБ")
        result = import_sources(content.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        return render_settings(request, error=str(error), status_code=400)
    finally:
        await upload.close()
    return RedirectResponse(
        f"/settings?imported={result['added']}&skipped={result['skipped']}",
        status_code=303,
    )


@app.get("/settings/export")
async def settings_export():
    try:
        store = load_store()
    except (OSError, ValueError) as error:
        return PlainTextResponse(
            f"{error}. Проверьте файл diagnostic_sources.json или удалите его.",
            status_code=400,
        )
    content = json.dumps(store, ensure_ascii=False, indent=2) + "\n"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="diagnostic_sources.json"'},
    )


@app.post("/settings/source")
async def settings_save_source(request: Request):
    form_data = await request.form()
    validate_csrf(form_data)
    source_id = form_text(form_data, "source_id") or None
    values = {
        "name": form_text(form_data, "name"),
        "product": form_text(form_data, "product"),
        "level": form_text(form_data, "level"),
        "example_url": form_text(form_data, "example_url"),
        "sample_value": form_text(form_data, "sample_value"),
        "minutes_before": form_text(form_data, "minutes_before", "2"),
        "minutes_after": form_text(form_data, "minutes_after", "90"),
    }
    try:
        source = save_source(values, source_id=source_id)
    except (OSError, ValueError) as error:
        return render_settings(
            request,
            overrides={source_id: values} if source_id else None,
            draft=values if not source_id else None,
            error=str(error),
            status_code=400,
        )
    return RedirectResponse(f"/settings?saved={source['id']}", status_code=303)


@app.post("/settings/source/delete")
async def settings_delete_source(request: Request):
    form_data = await request.form()
    validate_csrf(form_data)
    source_id = form_text(form_data, "source_id")
    try:
        delete_source(source_id)
    except (OSError, ValueError) as error:
        return render_settings(request, error=str(error), status_code=400)
    return RedirectResponse("/settings?deleted=1", status_code=303)


@app.post("/analyze")
async def analyze(request: Request):
    form_data = await request.form()
    validate_csrf(form_data)
    partial = wants_fragment(request)

    product = form_text(form_data, "product", "recording")
    ticket_text = form_text(form_data, "ticket_text")
    save_history = form_text(form_data, "save_history") == "1"
    corrections = {
        field_name: form_text(form_data, f"override_{field_name}")
        for field_name, _label in CORRECTION_FIELDS
    }
    picker_value = form_text(form_data, "override_event_datetime_picker")
    corrections["event_datetime_picker"] = picker_value
    form = {
        "product": product,
        "window": form_text(form_data, "window", "60"),
        "ticket_text": ticket_text,
        "save_history": save_history,
        "corrections": corrections,
    }

    try:
        if not ticket_text:
            raise ValueError("Вставьте текст заявки")
        if len(ticket_text) > MAX_TICKET_LENGTH:
            raise ValueError("Текст заявки превышает 200 000 символов")
        window = parse_window(form_data)
        modules = validate_product(product)
        form["dynamic_product"] = is_managed(product)
        if picker_value:
            corrections["event_datetime"] = normalize_datetime_picker(picker_value)
        effective_text = build_corrected_text(ticket_text, corrections)
        if is_managed(product):
            result = run_dynamic_ticket(
                ticket_text,
                product,
                "number",
                window,
                input_file="web",
                save_history=save_history,
                parse_text=effective_text,
            )
        else:
            result = run_ticket(
                ticket_text,
                open_arg=",".join(modules),
                window=window,
                input_file="web",
                save_history=save_history,
                write_diagnostics=False,
                parse_text=effective_text,
            )
    except (OSError, ValueError) as error:
        return render_index(
            request,
            form=form,
            error=str(error),
            status_code=400,
            partial=partial,
        )

    return render_index(
        request,
        form=form,
        result=result_view(result, "Первичная диагностика"),
        effective_ticket_text=effective_text,
        has_uuid_level=has_uuid_sources(product) or product == "recording",
        partial=partial,
    )


@app.post("/secondary")
async def secondary(request: Request):
    form_data = await request.form()
    validate_csrf(form_data)
    partial = wants_fragment(request)

    product = form_text(form_data, "product", "recording")
    effective_text = form_text(form_data, "effective_ticket_text")
    call_uuid = form_text(form_data, "call_uuid")
    mode = form_text(form_data, "secondary_mode", "mgw")
    form = {
        "product": product,
        "window": form_text(form_data, "window", "60"),
        "ticket_text": effective_text,
        "save_history": False,
        "corrections": {},
        "dynamic_product": False,
    }

    primary_result = None
    try:
        if not effective_text or len(effective_text) > MAX_TICKET_LENGTH:
            raise ValueError("Текст заявки отсутствует или слишком велик")
        window = parse_window(form_data)
        primary_modules = validate_product(product)
        form["dynamic_product"] = is_managed(product)
        if is_managed(product):
            if not has_uuid_sources(product):
                raise ValueError("Для этого продукта не настроен поиск по UUID")
            primary_result = run_dynamic_ticket(
                effective_text,
                product,
                "number",
                window,
                input_file="web-secondary",
            )
            secondary_result = run_dynamic_ticket(
                effective_text,
                product,
                "uuid",
                window,
                input_file="web-secondary",
                call_uuid=call_uuid,
            )
        else:
            if product != "recording":
                raise ValueError("Вторичная UUID-диагностика доступна только для продукта «Запись»")
            if mode not in SECONDARY_MODULES:
                raise ValueError("Неизвестный режим вторичной диагностики")
            primary_result = run_ticket(
                effective_text,
                open_arg=",".join(primary_modules),
                window=window,
                input_file="web-secondary",
                save_history=False,
                write_diagnostics=False,
            )
            secondary_result = run_ticket(
                effective_text,
                open_arg=",".join(SECONDARY_MODULES[mode]),
                window=window,
                input_file="web-secondary",
                save_history=False,
                write_diagnostics=False,
                call_uuid=call_uuid,
            )
    except (OSError, ValueError) as error:
        return render_index(
            request,
            form=form,
            result=(
                result_view(primary_result, "Первичная диагностика")
                if primary_result
                else None
            ),
            error=str(error),
            effective_ticket_text=effective_text,
            secondary_form={"call_uuid": call_uuid, "mode": mode},
            has_uuid_level=has_uuid_sources(product) or product == "recording",
            status_code=400,
            partial=partial,
        )

    return render_index(
        request,
        form=form,
        result=result_view(primary_result, "Первичная диагностика"),
        secondary_result=result_view(secondary_result, "Вторичная диагностика по UUID"),
        effective_ticket_text=effective_text,
        secondary_form={"call_uuid": call_uuid, "mode": mode},
        has_uuid_level=has_uuid_sources(product) or product == "recording",
        partial=partial,
    )


@app.post("/batch")
async def batch(request: Request):
    form_data = await request.form()
    validate_csrf(form_data)
    upload = form_data.get("table_file")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return render_index(request, error="Выберите таблицу для обработки", status_code=400)

    suffix = Path(upload.filename).suffix.lower()
    if suffix not in ALLOWED_TABLE_SUFFIXES:
        await upload.close()
        return render_index(
            request,
            error="Поддерживаются файлы XLSX, XLSM, CSV и TSV",
            status_code=400,
        )

    temp_dir = Path(tempfile.mkdtemp(prefix="l2tool-web-"))
    input_path = temp_dir / f"input{suffix}"
    output_path = temp_dir / "result.cleaned.xlsx"

    try:
        content = await upload.read(MAX_UPLOAD_SIZE + 1)
        if len(content) > MAX_UPLOAD_SIZE:
            raise ValueError("Файл превышает допустимый размер 25 МБ")
        file_descriptor = os.open(input_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(file_descriptor, "wb") as destination:
            destination.write(content)
        process_table(input_path, output_path)
    except (OSError, TableFormatError, ValueError) as error:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return render_index(request, error=str(error), status_code=400)
    finally:
        await upload.close()

    download_stem = Path(upload.filename).stem[:80] or "lost-calls"
    return FileResponse(
        output_path,
        filename=f"{download_stem}.cleaned.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=BackgroundTask(shutil.rmtree, temp_dir, ignore_errors=True),
    )


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


def main():
    parser = argparse.ArgumentParser(description="Локальный веб-интерфейс l2tool")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error("--port должен быть в диапазоне 1..65535")

    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
