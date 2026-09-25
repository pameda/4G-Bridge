#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if /usr/bin/git grep -InE \
  '(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|password[[:space:]]*=[[:space:]]*[^"[:space:]]+)' \
  -- ':!script/scan_sensitive.sh'; then
  echo "Potential secret detected." >&2
  exit 1
fi

echo "Sensitive-data pattern scan passed."
