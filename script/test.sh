#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT_DIR/.venv/bin/python"

"$ROOT_DIR/.venv/bin/ruff" format --check "$ROOT_DIR"
"$ROOT_DIR/.venv/bin/ruff" check "$ROOT_DIR"
"$ROOT_DIR/.venv/bin/mypy" "$ROOT_DIR/src/fourg_bridge"
"$PYTHON" -m pytest "$ROOT_DIR/tests"
