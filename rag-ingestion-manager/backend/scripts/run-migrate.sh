#!/bin/sh
set -e
exec python -m src.shared.db.migrate
