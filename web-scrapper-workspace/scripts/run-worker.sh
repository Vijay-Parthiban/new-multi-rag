#!/bin/sh
set -e

REDIS_URL="${REDIS_URL:-redis://redis:6379/0}"
exec rq worker crawl scrape scrape-page --url "$REDIS_URL"
