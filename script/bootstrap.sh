#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT_DIR/.toolchain/python-3.14.7/bin/python3.14"
VENV="$ROOT_DIR/.venv"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing project-local Python 3.14.7. See TESTING.md for the verified source build." >&2
  exit 1
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install \
  --index-url https://pypi.org/simple \
  --require-hashes \
  --only-binary=:all: \
  -r "$ROOT_DIR/requirements-arm64.lock"
"$VENV/bin/python" -m pip install --no-build-isolation --no-deps --editable "$ROOT_DIR"
