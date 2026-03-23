#!/usr/bin/env bash
set -euo pipefail

# Builds a standalone desktop binary with PyInstaller.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "${SCRIPT_DIR}/../.venv/bin/python" ]]; then
  PYTHON_BIN="${SCRIPT_DIR}/../.venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

"${PYTHON_BIN}" -m PyInstaller \
  --noconfirm \
  --onefile \
  --name StockfishPositionExplorer \
  app.py

echo "Build complete: dist/StockfishPositionExplorer"
