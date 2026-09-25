#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON="$ROOT_DIR/.venv/bin/python"
elif command -v python3.14 >/dev/null 2>&1; then
  PYTHON="$(command -v python3.14)"
else
  PYTHON="$(command -v python3)"
fi

"$PYTHON" -m ruff format --check "$ROOT_DIR"
"$PYTHON" -m ruff check "$ROOT_DIR"
"$PYTHON" -m mypy "$ROOT_DIR/src/fourg_bridge"
"$PYTHON" -m pytest "$ROOT_DIR/tests"
