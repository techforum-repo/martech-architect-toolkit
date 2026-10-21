#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

echo ""
echo "======================================"
echo "Web Technology Inspector - Linux/macOS"
echo "======================================"
echo ""

if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv .venv
fi

PYTHON=".venv/bin/python"

echo "Checking dependencies..."
"$PYTHON" -m pip install -r requirements.txt

echo "Checking Playwright Chromium..."
"$PYTHON" -m playwright install chromium

echo "Starting application..."
exec "$PYTHON" launcher.py
