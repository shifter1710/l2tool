import json
import os
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4


HISTORY_ROOT = Path("history")
INDEX_NAME = "index.json"


def ticket_numbers(ctx):
    numbers = []
    for field in ("msisdn", "phone_a", "phone_b"):
        value = ctx.get(field)
        if value and value not in numbers:
            numbers.append(value)
    return numbers


def load_index(history_root=HISTORY_ROOT):
    index_path = Path(history_root) / INDEX_NAME
    if not index_path.exists():
        return {}

    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(data, dict):
        return {}

    return {
        str(number): [str(path) for path in paths if isinstance(path, str)]
        for number, paths in data.items()
        if isinstance(paths, list)
    }


def find_matches(ctx, history_root=HISTORY_ROOT):
    index = load_index(history_root)
    return {
        number: index[number]
        for number in ticket_numbers(ctx)
        if number in index and index[number]
    }


def format_matches(matches):
    lines = ["--- History matches ---"]

    if not matches:
        lines.append("No matches")
    else:
        for number, paths in matches.items():
            lines.append(f"{number}:")
            lines.extend(f"  - {path}" for path in paths)

    lines.append("-----------------------")
    return lines


def save_ticket_history(
    ctx,
    input_file,
    raw_ticket,
    links_by_module,
    history_root=HISTORY_ROOT,
    now=None,
    uuid_factory=None,
):
    history_root = Path(history_root)
    uuid_factory = uuid_factory or uuid4
    archive_uuid = uuid_factory()
    shortid = archive_uuid.hex[:8]
    event_date = _archive_date(ctx, now)
    main_number = (
        ctx.get("msisdn")
        or ctx.get("phone_a")
        or ctx.get("phone_b")
        or "unknown"
    )

    archive_path = (
        history_root
        / f"{event_date:%Y}"
        / f"{event_date:%m}"
        / f"{event_date:%Y-%m-%d}_{main_number}_{shortid}.yaml"
    )
    _atomic_write_text(
        archive_path,
        _render_yaml(
            archive_uuid=str(archive_uuid),
            created_at=(now or datetime.now().astimezone()).isoformat(),
            input_file=str(input_file),
            ctx=ctx,
            modules=list(links_by_module),
            links_by_module=links_by_module,
            raw_ticket=raw_ticket,
        ),
    )

    archive_path_text = archive_path.as_posix()
    index = load_index(history_root)
    for number in ticket_numbers(ctx):
        paths = index.setdefault(number, [])
        if archive_path_text not in paths:
            paths.append(archive_path_text)

    index_path = history_root / INDEX_NAME
    _atomic_write_text(
        index_path,
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )

    return archive_path


def _archive_date(ctx, now):
    event_time = ctx.get("event_time")
    if isinstance(event_time, datetime):
        return event_time.date()

    event_date = ctx.get("event_date")
    if isinstance(event_date, date):
        return event_date

    current = now or datetime.now().astimezone()
    return current.date()


def _atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None

    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_file.write(text)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
            tmp_path = Path(tmp_file.name)

        tmp_path.replace(path)
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


def _string_value(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _quote(value):
    return json.dumps(_string_value(value), ensure_ascii=False)


def _render_yaml(
    archive_uuid,
    created_at,
    input_file,
    ctx,
    modules,
    links_by_module,
    raw_ticket,
):
    lines = [
        f"uuid: {_quote(archive_uuid)}",
        f"created_at: {_quote(created_at)}",
        f"input_file: {_quote(input_file)}",
        "",
        "parsed:",
        f"  msisdn: {_quote(ctx.get('msisdn'))}",
        f"  phone_a: {_quote(ctx.get('phone_a'))}",
        f"  phone_b: {_quote(ctx.get('phone_b'))}",
        f"  event_time: {_quote(ctx.get('event_time'))}",
        f"  region: {_quote(ctx.get('region'))}",
        f"  timezone: {_quote(ctx.get('tz'))}",
        "",
        "modules:",
    ]

    if modules:
        lines.extend(f"  - {module}" for module in modules)
    else:
        lines.append("  []")

    lines.extend(["", "links:"])
    if links_by_module:
        for module, links in links_by_module.items():
            if len(links) == 1:
                lines.append(f"  {module}: {_quote(links[0])}")
            else:
                lines.append(f"  {module}:")
                lines.extend(f"    - {_quote(link)}" for link in links)
    else:
        lines.append("  {}")

    lines.extend(["", "raw_ticket: |"])
    raw_lines = raw_ticket.splitlines()
    if raw_lines:
        lines.extend(f"  {line}" for line in raw_lines)
    else:
        lines.append("")

    return "\n".join(lines) + "\n"
