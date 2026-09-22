#!/usr/bin/env bash
# run.sh — by idqwixxa

set -e
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "[ERROR] $PYTHON не найден. Установи Python 3.10+."
    exit 1
fi

if ! "$PYTHON" -c "import requests, colorama" >/dev/null 2>&1; then
    echo "[*] Устанавливаю зависимости из requirements.txt…"
    "$PYTHON" -m pip install -r requirements.txt
fi

exec "$PYTHON" main.py "$@"