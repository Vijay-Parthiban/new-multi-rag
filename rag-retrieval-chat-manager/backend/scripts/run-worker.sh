#!/bin/sh
set -e

REDIS_URL="${REDIS_URL:-redis://redis:6379/0}"
QUEUE="${RQ_EVAL_QUEUE:-eval}"

exec rq worker "$QUEUE" --url "$REDIS_URL"
