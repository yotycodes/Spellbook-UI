#!/usr/bin/env bash
# Spellbook launcher — macOS and Linux.
#
#   ./launch.sh              app mode: a desktop window
#   ./launch.sh --web        web mode: server only; open http://127.0.0.1:7872 in your browser
#   ./launch.sh --port N     custom port (default 7872; SPELLBOOK_PORT also works)
#
# First run: creates .venv and installs the pinned requirements (Python 3.10+ required).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/.venv"

if [ "$(uname)" = "Darwin" ]; then PYS=(python3.13 python3.12 python3.11 python3); else PYS=(python3 python3.13 python3.12 python3.11); fi

PYBIN=""
for c in "${PYS[@]}"; do
  if command -v "$c" > /dev/null 2>&1; then PYBIN="$c"; break; fi
done
[ -n "$PYBIN" ] || { echo "Python 3.10+ is required. Install it from python.org (macOS) or your package manager (Linux)." >&2; exit 1; }

if [ ! -x "$VENV/bin/python" ]; then
  echo "First run: creating Spellbook's Python environment (one time, a few minutes)…"
  "$PYBIN" -m venv "$VENV"
  "$VENV/bin/python" -m pip install --upgrade pip --quiet
  "$VENV/bin/python" -m pip install -r "$HERE/requirements.txt"
  echo "Environment ready."
fi

export PYTHONDONTWRITEBYTECODE=1
export SPELLBOOK_PORT="${SPELLBOOK_PORT:-7872}"

WEB=0
while [ $# -gt 0 ]; do
  case "$1" in
    --web) WEB=1 ;;
    --port) export SPELLBOOK_PORT="$2"; shift ;;
    *) echo "Unknown option: $1 (use --web or --port N)" >&2; exit 2 ;;
  esac
  shift
done

if [ "$WEB" = "1" ]; then
  exec "$VENV/bin/python" "$HERE/server.py" --no-window --port "$SPELLBOOK_PORT"
else
  exec "$VENV/bin/python" "$HERE/server.py" --window --port "$SPELLBOOK_PORT"
fi
