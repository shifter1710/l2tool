#!/usr/bin/env python3

import argparse
from pathlib import Path

from core import history
from core import parser
from core.timezones import resolve_timezone
from core.utils import open_url, hash_phone

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


def main():
    ap = argparse.ArgumentParser(description="L2 ticket helper")
    ap.add_argument("--file", default=DEFAULT_FILE, help="Path to ticket text file")
    ap.add_argument(
        "--open",
        default=DEFAULT_OPEN,
        help="Modules: zapis,bff,myconnect,myconnect_call or all",
    )
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW, help="Window in minutes for Grafana")
    ap.add_argument("--no-history", action="store_true", help="Do not save a new history YAML")
    ap.add_argument("--dry-run", action="store_true", help="Print context, history matches, and links only")

    args = ap.parse_args()

    try:
        text = read_file(args.file)
    except FileNotFoundError:
        ap.error(f"ticket file not found: {args.file}")

    ctx = parser.parse(text)
    ctx["tz"] = resolve_timezone(ctx.get("region"))
    ctx["window"] = args.window

    print("\n--- Parsed context ---")
    for k, v in ctx.items():
        print(f"{k}: {v}")

    if ctx.get("msisdn"):
        print(f"msisdn_hash: {hash_phone(ctx['msisdn'])}")

    print("----------------------\n")

    history.print_matches(history.find_matches(ctx))
    print()

    selected = resolve_modules(args.open)
    links_by_module = {}

    for name in selected:
        mod = MODULES[name]

        try:
            links = mod.build(ctx)
        except Exception as e:
            print(f"[ERROR] Module failed: {name}: {e}")
            continue

        if links:
            links_by_module[name] = links

    if not links_by_module:
        print("No URLs generated")
        return

    for name, links in links_by_module.items():
        print(f"[{name}]")
        for url in links:
            print(url)

    if not args.dry_run and not args.no_history:
        path = history.write_history(
            ctx=ctx,
            input_file=args.file,
            raw_ticket=text,
            selected_modules=list(links_by_module.keys()),
            links_by_module=links_by_module,
        )
        print(f"\nHistory saved: {path.as_posix()}")

    if args.dry_run:
        return

    for name, links in links_by_module.items():
        for url in links:
            if getattr(MODULES[name], "OPEN_IN_CHROME", False):
                from core.utils import open_url_chrome
                open_url_chrome(url)
            else:
                open_url(url)


if __name__ == "__main__":
    main()
