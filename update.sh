#!/usr/bin/env bash
# Update in place (keeps data/, .env). Usage: ./update.sh  or  ./update.sh path/to/tarbiyah-hub.zip
cd "$(dirname "$0")"
.venv/bin/python -m tarbiyah stop
if [ -n "$1" ]; then .venv/bin/python -m tarbiyah update --zip "$1"; else .venv/bin/python -m tarbiyah update; fi
./start.sh
