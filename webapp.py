#!/usr/bin/env python3

import argparse
import os
import secrets
import shutil
import tempfile
import threading
import webbrowser
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask
from starlette.datastructures import UploadFile
from starlette.middleware.trustedhost import TrustedHostMiddleware

from core import history
from core.lost_calls_table import TableFormatError, process_table
from core.products import available_products, product_title, resolve_product_modules
from gtool import MODULE_TITLES, RunResult, run_ticket


ROOT_DIR = Path(__file__).resolve().parent
LOCAL_HOSTS = ["127.0.0.1", "localhost"]
MAX_TICKET_LENGTH = 200_000
MAX_UPLOAD_SIZE = 25 * 1024 * 1024
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
        "default-src 'self'; style-src 'self'; img-src 'self' data:; "
        "frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


def product_options():
    return [
        {
            "key": key,
            "title": product_title(key),
            "enabled": bool(resolve_product_modules(key)),
        }
        for key in available_products()
    ]


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
        },
        "result": None,
        "secondary_result": None,
        "error": None,
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
    modules = resolve_product_modules(product)
    if not modules:
        raise ValueError(f"Для продукта «{product_title(product)}» пока нет настроенных сервисов")
    return modules


def build_corrected_text(ticket_text, corrections):
    correction_lines = [
        f"{label}: {corrections[field_name]}"
        for field_name, label in CORRECTION_FIELDS
        if corrections.get(field_name)
    ]
    return "\n".join([*correction_lines, ticket_text])


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
    return {
        "title": title,
        "status": result.status,
        "status_title": {
            "success": "Готово",
            "partial": "Частичный результат",
            "failed": "Нужна проверка",
        }.get(result.status, result.status),
        "fields": [
            ("Номер клиента", format_value(ctx.get("msisdn"))),
            ("Номер А", format_value(ctx.get("phone_a"))),
            ("Номер Б", format_value(ctx.get("phone_b"))),
            ("Дата и время", event_value(ctx)),
            ("Регион", format_value(ctx.get("region"))),
            ("Часовой пояс", format_value(ctx.get("tz"))),
        ],
        "services": [
            {
                "key": module_name,
                "title": MODULE_TITLES.get(module_name, module_name),
                "links": links,
            }
            for module_name, links in result.links_by_module.items()
        ],
        "warnings": warnings,
        "history": history.find_matches(ctx),
    }


def render_index(request, *, status_code=200, **values):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=page_context(request, **values),
        status_code=status_code,
    )


@app.get("/")
async def index(request: Request):
    return render_index(request)


@app.post("/analyze")
async def analyze(request: Request):
    form_data = await request.form()
    validate_csrf(form_data)

    product = form_text(form_data, "product", "recording")
    ticket_text = form_text(form_data, "ticket_text")
    save_history = form_text(form_data, "save_history") == "1"
    corrections = {
        field_name: form_text(form_data, f"override_{field_name}")
        for field_name, _label in CORRECTION_FIELDS
    }
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
        effective_text = build_corrected_text(ticket_text, corrections)
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
        return render_index(request, form=form, error=str(error), status_code=400)

    return render_index(
        request,
        form=form,
        result=result_view(result, "Первичная диагностика"),
        effective_ticket_text=effective_text,
    )


@app.post("/secondary")
async def secondary(request: Request):
    form_data = await request.form()
    validate_csrf(form_data)

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
    }

    primary_result = None
    try:
        if not effective_text or len(effective_text) > MAX_TICKET_LENGTH:
            raise ValueError("Текст заявки отсутствует или слишком велик")
        window = parse_window(form_data)
        primary_modules = validate_product(product)
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
            status_code=400,
        )

    return render_index(
        request,
        form=form,
        result=result_view(primary_result, "Первичная диагностика"),
        secondary_result=result_view(secondary_result, "Вторичная диагностика по UUID"),
        effective_ticket_text=effective_text,
        secondary_form={"call_uuid": call_uuid, "mode": mode},
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
