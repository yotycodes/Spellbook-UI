#!/usr/bin/env zsh
# Launch the isolated Spellbook Beta development server.
# Usage: ./run_spellbook.sh [--port N]

HERE="${0:A:h}"
ROOT="${HERE:h}"
VENV="$HERE/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  print -u2 "Spellbook Beta's private Python environment is missing: $VENV"
  exit 1
fi

PORT=${SPELLBOOK_PORT:-7872}
if [[ "$1" == "--port" && -n "$2" ]]; then
  PORT=$2
fi

PYTHON="$VENV/bin/python"

export SPELLBOOK_APP_DIR="$ROOT/.beta-data"
export SPELLBOOK_POSE_KIT="$ROOT/.pose-kit"
export PYTHONDONTWRITEBYTECODE=1
unset VIRTUAL_ENV VIRTUAL_ENV_PROMPT VIRTUAL_ENV_DISABLE_PROMPT
cd "$HERE" || exit 1
exec "$PYTHON" "$HERE/server.py" --port "$PORT" --window
