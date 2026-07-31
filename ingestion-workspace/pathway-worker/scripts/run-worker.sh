#!/bin/sh
# Start the Pathway source-sync worker

cd /app/ingestion-workspace/pathway-worker

# Ensure the ingestion-backend module is available on PYTHONPATH
# (needed for shared DB models, S3 client, etc.)
export PYTHONPATH="/app/ingestion-workspace/pathway-worker/src:/app/ingestion-workspace/ingestion-backend/src:${PYTHONPATH}"

exec python -m pathway_worker.main