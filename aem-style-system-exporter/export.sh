
#!/bin/sh
set -eu

cd "$(dirname "$0")"

echo "=========================================="
echo " AEM STYLE SYSTEM EXPORTER"
echo "=========================================="

if ! command -v node >/dev/null 2>&1; then
  echo "[ERROR] Node.js is not installed."
  exit 1
fi

if ! node -e "process.exit(+process.versions.node.split('.')[0] >= 22 ? 0 : 1)"; then
  echo "[ERROR] Node.js 22 or later is required (found $(node -v))."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "[ERROR] npm is not installed."
  exit 1
fi

echo "[1/3] Checking dependencies..."

if ! node -e "require.resolve('exceljs'); require.resolve('postcss'); require.resolve('postcss-selector-parser')" >/dev/null 2>&1; then
  echo "[INFO] Installing dependencies..."
  npm install --no-audit --no-fund
else
  echo "[OK] Dependencies already installed."
fi

echo "[2/3] Running AEM and FE export..."

set +e
node src/master-exporter.js "$@"
STATUS=$?
set -e

echo "[3/3] Export finished."

if [ "$STATUS" -eq 0 ]; then
  echo "[SUCCESS] Export completed."
elif [ "$STATUS" -eq 2 ]; then
  echo "[WARNING] Export completed with validation issues."
else
  echo "[ERROR] Export failed."
fi

exit "$STATUS"
