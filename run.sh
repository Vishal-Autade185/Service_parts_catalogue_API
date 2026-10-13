#!/usr/bin/env bash
# Start the API without Docker: bash run.sh
# Works on Linux, macOS and Windows (Git Bash). Optional: PYTHON=/path/to/python, DATA_DIR, ROOT_PN.
set -euo pipefail
cd "$(dirname "$0")"

# First interpreter that really runs and is Python 3.9+ (Windows' "python3" may be a Store stub).
PY=""
for cand in ${PYTHON:-} python3 python py; do
  if command -v "$cand" >/dev/null 2>&1 \
     && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    PY="$cand"
    break
  fi
done
[ -n "$PY" ] || { echo "ERROR: Python 3.9+ not found. Install it or set PYTHON=/path/to/python." >&2; exit 1; }

# The venv's interpreter: bin/ on Linux and macOS, Scripts/ on Windows.
venv_python() {
  for p in .venv/bin/python .venv/Scripts/python.exe; do
    [ -x "$p" ] && { echo "$p"; return 0; }
  done
  return 1
}

if "$PY" -m venv .venv >/dev/null 2>&1 && RUN_PY="$(venv_python)"; then
  "$RUN_PY" -m pip install -q --upgrade pip
  "$RUN_PY" -m pip install -q -r requirements.txt
else
  echo "venv unavailable; installing packages for the current user instead." >&2
  RUN_PY="$PY"
  "$PY" -m pip install -q --user -r requirements.txt \
    || "$PY" -m pip install -q --user --break-system-packages -r requirements.txt
fi

exec "$RUN_PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
