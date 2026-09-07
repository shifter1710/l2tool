#!/usr/bin/env python3
"""Диагностические ссылки по истории звонков, вытянутой из истории баланса.

Вход — текст, который формирует внешний скрипт детализации: строки событий
с датой и временем (МСК), направлением, номером, длительностью и типом
звонка. Тройки событий переадресации (исходящий на сервисный номер, сама
переадресация и входящая нога звонящего) схлопываются в один звонок.
"""

import argparse
import sys

import gtool


def main():
    ap = argparse.ArgumentParser(
        description="Диагностические ссылки по истории звонков из истории баланса"
    )
    ap.add_argument(
        "--file",
        default=gtool.CALL_HISTORY_DEFAULT_FILE,
        help="Путь к файлу истории звонков",
    )
    ap.add_argument("--msisdn", help="Номер клиента из заявки (7XXXXXXXXXX)")
    ap.add_argument(
        "--open",
        default=None,
        help=f"Сервисы: {','.join(gtool.MODULES)}, ключи блоков или all",
    )
    ap.add_argument("--product", choices=gtool.available_products(), help="Product profile")
    ap.add_argument(
        "--window",
        type=int,
        default=None,
        help="Window in minutes for Grafana",
    )
    ap.add_argument(
        "--max-calls",
        type=int,
        default=None,
        help="Максимум звонков в выводе",
    )

    args = ap.parse_args()

    if args.product and args.open:
        ap.error("Use either --product or --open, not both")
    if args.window is not None and args.window < 0:
        ap.error("--window must be non-negative")
    if args.max_calls is not None and args.max_calls < 1:
        ap.error("--max-calls must be positive")

    product_key = args.product
    interactive = sys.stdin.isatty()

    if not product_key and not args.open and interactive:
        try:
            product_key = gtool.prompt_product()
        except ValueError as error:
            print(str(error))
            return 2

    open_arg = args.open or gtool.configured_call_history_open()
    window = args.window if args.window is not None else gtool.configured_default_window()
    max_calls = args.max_calls
    if max_calls is None:
        max_calls = gtool.configured_call_history_max_calls()
    if product_key:
        open_arg = gtool.product_open_arg(product_key)
        if open_arg is None:
            return 2

    try:
        text = gtool.read_file(args.file)
    except FileNotFoundError:
        ap.error(f"call history file not found: {args.file}")

    msisdn = args.msisdn
    if not msisdn and interactive:
        msisdn = input("Номер клиента из заявки (Enter — пропустить): ").strip() or None

    try:
        result = gtool.run_call_history(
            text,
            msisdn=msisdn,
            open_arg=open_arg,
            window=window,
            max_calls=max_calls,
        )
    except ValueError as error:
        print(str(error))
        return 2

    print("\n" + "\n".join(gtool.format_call_history_result(result)))

    return 0 if result.status == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
