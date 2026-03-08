#!/usr/bin/env bash
set -euo pipefail

echo "[Task1] Environment checks"

check_cmd() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then
    echo "  - $name: OK ($(command -v "$name"))"
  else
    echo "  - $name: MISSING"
  fi
}

check_cmd python3
check_cmd klayout
check_cmd magic
check_cmd ngspice

echo "Done."
