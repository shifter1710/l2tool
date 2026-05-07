import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

HISTORY_DIR = Path("history")
INDEX_PATH = HISTORY_DIR / "index.json"


def ticket_numbers(ctx):
    seen = set()
    numbers = []

    for key in ("msisdn", "phone_a", "phone_b"):
        number = ctx.get(key)
        if number and number not in seen:
            seen.add(number)
            numbers.append(number)

    return numbers


def main_number(ctx):
    return ctx.get("msisdn") or ctx.get("phone_a") or ctx.get("phone_b") or "unknown"


def load_index():
    if not INDEX_PATH.exists():
        return {}

    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def find_matches(ctx):
    index = load_index()
    return {
        number: index[number]
        for number in ticket_numbers(ctx)
        if number in index and index[number]
    }


def print_matches(matches):
    print("--- History matches ---")

    if not matches:
        print("No matches")
    else:
        for number, paths in matches.items():
            print(f"{number}:")
            for path in paths:
                print(f"  - {path}")

    print("-----------------------")


def yaml_scalar(value):
    if value is None:
        return '""'

    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def yaml_list(items):
    return "\n".join(f"  - {yaml_scalar(item)}" for item in items)


def yaml_links(links_by_module):
    lines = ["links:"]

    for module_name, links in links_by_module.items():
        if len(links) == 1:
            lines.append(f"  {module_name}: {yaml_scalar(links[0])}")
        else:
            lines.append(f"  {module_name}:")
            for link in links:
                lines.append(f"    - {yaml_scalar(link)}")

    return "\n".join(lines)


def yaml_raw_ticket(raw_ticket):
    if not raw_ticket:
        return "raw_ticket: |\n"

    body = "\n".join(f"  {line}" for line in raw_ticket.splitlines())
    return f"raw_ticket: |\n{body}\n"


def history_path(ctx, shortid):
    event_date = ctx["event_time"].date()
    return (
        HISTORY_DIR
        / f"{event_date:%Y}"
        / f"{event_date:%m}"
        / f"{event_date:%Y-%m-%d}_{main_number(ctx)}_{shortid}.yaml"
    )


def write_history(ctx, input_file, raw_ticket, selected_modules, links_by_module):
    shortid = uuid4().hex[:8]
    path = history_path(ctx, shortid)
    path.parent.mkdir(parents=True, exist_ok=True)

    content = "\n".join([
        'uuid: ""',
        f"created_at: {yaml_scalar(datetime.now().astimezone().isoformat(timespec='seconds'))}",
        f"input_file: {yaml_scalar(input_file)}",
        "",
        "parsed:",
        f"  msisdn: {yaml_scalar(ctx.get('msisdn'))}",
        f"  phone_a: {yaml_scalar(ctx.get('phone_a'))}",
        f"  phone_b: {yaml_scalar(ctx.get('phone_b'))}",
        f"  event_time: {yaml_scalar(ctx.get('event_time'))}",
        f"  region: {yaml_scalar(ctx.get('region'))}",
        f"  timezone: {yaml_scalar(ctx.get('tz'))}",
        "",
        "modules:",
        yaml_list(selected_modules),
        "",
        yaml_links(links_by_module),
        "",
        yaml_raw_ticket(raw_ticket).rstrip("\n"),
        "",
    ])

    path.write_text(content, encoding="utf-8")
    update_index(ctx, path)
    return path


def update_index(ctx, path):
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    index = load_index()
    path_text = path.as_posix()

    for number in ticket_numbers(ctx):
        paths = index.setdefault(number, [])
        if path_text not in paths:
            paths.append(path_text)

    INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
