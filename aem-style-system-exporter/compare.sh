#!/bin/sh
# Opens the compare page (what changed between two saved exports) in the
# browser. With arguments, compares on the command line instead:
#   sh compare.sh --list
#   sh compare.sh <before> <after>
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

if ! node -e "require.resolve('exceljs')" >/dev/null 2>&1; then
  echo "[INFO] Installing dependencies..."
  npm install --no-audit --no-fund
fi

exec node src/compare.js "$@"
