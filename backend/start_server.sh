#!/usr/bin/env bash
set -euo pipefail

# Detect port or default
PORT=${PORT:-8000}
HOST=${HOST:-0.0.0.0}

# Simple health endpoint start using uvicorn
exec uvicorn main:app --host "$HOST" --port "$PORT" --log-level info --workers 1
