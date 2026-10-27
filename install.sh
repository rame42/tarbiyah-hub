#!/usr/bin/env bash
# One-time installation (Linux / macOS)
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
$PY -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
[ -d .venv ] || $PY -m venv .venv
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt
[ -f .env ] || { cp .env.example .env; echo "Created .env (add optional keys there)."; }
.venv/bin/python -m tarbiyah init
echo "Installation complete. Start with: ./start.sh"
