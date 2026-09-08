#!/bin/sh
set -e

HOST="${API_HOST:-0.0.0.0}"
PORT="${API_PORT:-8001}"

exec uvicorn rag_api.main:app --host "$HOST" --port "$PORT"
