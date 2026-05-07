#!/usr/bin/env python3

import argparse
from pathlib import Path

from core import parser
from core.timezones import resolve_timezone
from core.utils import open_url, hash_phone

import modules.bff_logs_opensearch as bff_logs_opensearch
import modules.find_call_in_logs as find_call_in_logs
import modules.profile_not_found_myconnect as profile_not_found_myconnect

MODULES = {
    "find_call_in_logs": find_call_in_logs,
    "bff_logs_opensearch": bff_logs_opensearch,
    "profile_not_found_myconnect": profile_not_found_myconnect,
}

ALIASES = {
    "grafana": "find_call_in_logs",
    "logs": "bff_logs_opensearch",
    "myconnect": "profile_not_found_myconnect",
}


def read_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="L2 ticket helper")
    ap.add_argument("--file", required=True, help="Path to ticket text file")
    ap.add_argument(
        "--open",
        default="find_call_in_logs",
        help=(
            "Modules: find_call_in_logs,bff_logs_opensearch,"
            "profile_not_found_myconnect or all"
        ),
    )
    ap.add_argument("--window", type=int, default=60, help="Window in minutes for Grafana")

    args = ap.parse_args()

    text = read_file(args.file)

    ctx = parser.parse(text)
    ctx["tz"] = resolve_timezone(ctx.get("region"))
    ctx["window"] = args.window

    print("\n--- Parsed context ---")
    for k, v in ctx.items():
        print(f"{k}: {v}")

    if ctx.get("msisdn"):
        print(f"msisdn_hash: {hash_phone(ctx['msisdn'])}")

    print("----------------------\n")

    selected = list(MODULES.keys()) if args.open == "all" else args.open.split(",")

    urls = []

    for raw_name in selected:
        raw_name = raw_name.strip()
        name = ALIASES.get(raw_name, raw_name)

        mod = MODULES.get(name)
        if not mod:
            print(f"[WARN] Unknown module: {raw_name}")
            continue

        try:
            for url in mod.build(ctx):
                urls.append((name, url))
        except Exception as e:
            print(f"[ERROR] Module failed: {name}: {e}")

    if not urls:
        print("No URLs generated")
        return

    for name, url in urls:
        print(f"[{name}]")
        print(url)
        if getattr(MODULES[name], "OPEN_IN_CHROME", False):
            from core.utils import open_url_chrome
            open_url_chrome(url)
        else:
            open_url(url)


if __name__ == "__main__":
    main()
