#!/bin/sh
# Opens the app (run exports, settings, history, compare) in the browser.
set -eu

cd "$(dirname "$0")"

if ! command -v node >/dev/null 2>&1; then
  echo "[ERROR] Node.js is not installed."
  exit 1
fi

if ! node -e "process.exit(+process.versions.node.split('.')[0] >= 22 ? 0 : 1)"; then
  echo "[ERROR] Node.js 22 or later is required (found $(node -v))."
  exit 1
fi

if ! node -e "require.resolve('exceljs'); require.resolve('postcss'); require.resolve('postcss-selector-parser')" >/dev/null 2>&1; then
  echo "[INFO] Installing dependencies..."
  npm install --no-audit --no-fund
fi

exec node src/app-server.js "$@"
