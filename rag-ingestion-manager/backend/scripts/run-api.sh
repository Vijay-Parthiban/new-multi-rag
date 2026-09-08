#!/bin/sh
set -e
exec uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
