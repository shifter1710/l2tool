#!/usr/bin/env python3

import argparse

from core.lost_calls_table import TableFormatError, process_table


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Создать очищенную XLSX-таблицу потерянных звонков "
            "со ссылками на Grafana"
        )
    )
    parser.add_argument("input", help="Исходный XLSX, XLSM, CSV или TSV")
    parser.add_argument(
        "--output",
        help="Выходной XLSX (по умолчанию <имя>.cleaned.xlsx рядом с исходником)",
    )
    parser.add_argument("--sheet", help="Имя листа исходного XLSX")
    parser.add_argument(
        "--window",
        type=int,
        default=60,
        help="Окно ссылки до и после старта звонка в минутах (по умолчанию 60)",
    )
    args = parser.parse_args()

    try:
        result = process_table(
            args.input,
            args.output,
            sheet_name=args.sheet,
            window=args.window,
        )
    except (FileNotFoundError, TableFormatError, ValueError) as error:
        parser.error(str(error))

    print(f"Обработано строк: {result.row_count}")
    print(f"Создано ссылок: {result.link_count}")
    for warning in result.warnings:
        print(f"[WARN] {warning}")
    print(f"Результат: {result.output_path}")


if __name__ == "__main__":
    main()
