#!/usr/bin/env python3

import argparse
from pathlib import Path

from core import parser
from core.timezones import resolve_timezone
from core.utils import open_url, hash_phone

import modules.grafana_call as grafana
import modules.logs_discover as logs
import modules.myconnect as myconnect

MODULES = {
    "grafana": grafana,
    "logs": logs,
}


def read_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="L2 ticket helper")
    ap.add_argument("--file", required=True, help="Path to ticket text file")
    ap.add_argument("--open", default="grafana", help="Modules: grafana,logs or all")
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

    for name in selected:
        name = name.strip()

        mod = MODULES.get(name)
        if not mod:
            print(f"[WARN] Unknown module: {name}")
            continue

        try:
            urls.extend(mod.build(ctx))
        except Exception as e:
            print(f"[ERROR] Module failed: {name}: {e}")

    if not urls:
        print("No URLs generated")
        return

    for url in urls:
        print(url)
        if name == "myconnect":
            from core.utils import open_url_chrome
            open_url_chrome(url)
        else:
            open_url(url)


if __name__ == "__main__":
    main()