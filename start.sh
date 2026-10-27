#!/usr/bin/env bash
# Start worker + dashboard in the background (Linux / macOS). Logs: data/logs/
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p data/logs
nohup .venv/bin/python -m tarbiyah worker >> data/logs/worker.out 2>&1 &
nohup .venv/bin/python -m tarbiyah web --host "${TH_HOST:-127.0.0.1}" --port "${TH_PORT:-8000}" >> data/logs/web.out 2>&1 &
sleep 3
echo "Tarbiyah Hub running at http://${TH_HOST:-127.0.0.1}:${TH_PORT:-8000}  (stop with ./stop.sh)"
