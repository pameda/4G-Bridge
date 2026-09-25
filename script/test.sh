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
cd "$ROOT_DIR"

"$PYTHON" -m ruff format --check "$ROOT_DIR"
"$PYTHON" -m ruff check "$ROOT_DIR"
"$PYTHON" -m mypy "$ROOT_DIR/src/fourg_bridge"
"$PYTHON" -m pytest "$ROOT_DIR/tests"
"$PYTHON" -m coverage report \
  --include='src/fourg_bridge/sms/*,src/fourg_bridge/imessage/formatter.py,src/fourg_bridge/network/data_session.py,src/fourg_bridge/network/traffic.py,src/fourg_bridge/network/failover.py,src/fourg_bridge/network/connectivity.py,src/fourg_bridge/storage/budget.py,src/fourg_bridge/storage/database.py,src/fourg_bridge/storage/settings.py,src/fourg_bridge/support/privacy.py' \
  --fail-under=90
