#!/usr/bin/env bash
# Запуск l2tool в один шаг: при первом запуске создаёт виртуальное окружение,
# устанавливает зависимости и открывает веб-интерфейс на http://127.0.0.1:8765.
# Дополнительные параметры передаются webapp.py: ./start.sh --port 9000 --no-browser
set -euo pipefail
cd "$(dirname "$0")"

PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "Не найден Python 3.10+. Установите его (например, python3.12) и запустите скрипт снова." >&2
  exit 1
fi

if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Требуется Python 3.10 или новее, найден $("$PYTHON" --version 2>&1)." >&2
  exit 1
fi

VENV_PYTHON=".venv/bin/python"

if [ ! -x "$VENV_PYTHON" ]; then
  echo "Создаю виртуальное окружение .venv …"
  "$PYTHON" -m venv .venv
fi

if ! "$VENV_PYTHON" -c "import fastapi, jinja2, openpyxl, uvicorn" >/dev/null 2>&1; then
  echo "Устанавливаю зависимости …"
  "$VENV_PYTHON" -m pip install --upgrade pip >/dev/null
  "$VENV_PYTHON" -m pip install -r requirements.txt
fi

exec "$VENV_PYTHON" webapp.py "$@"
