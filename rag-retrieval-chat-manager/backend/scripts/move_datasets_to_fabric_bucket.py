"""Move every dataset file out of a Knowledge Product bucket into `dataset_fabric_bucket`.

The ingestion service lists a Knowledge Product's document bucket whole, so a dataset
written there before this rule is read as a document, chunked and embedded into that
product's destinations. This script copies each such object into the dataset bucket, points
its `golden_datasets` row at the new place, and then deletes the old object. The delete is
what the ingestion fanout's DELETE sweep watches: on its next tick it purges that file's
chunks from every destination and drops its ledger row.

    python scripts/move_datasets_to_fabric_bucket.py           # report only
    python scripts/move_datasets_to_fabric_bucket.py --apply    # move

Run it with the same environment the API uses. It is idempotent: a row already in the
dataset bucket is skipped.
"""

from __future__ import annotations

import argparse
import asyncio

from eval_core.dataset_storage import (
    DatasetStorageError,
    delete_dataset,
    get_dataset,
    put_dataset,
    resolve_bucket,
)
from rag_db.models.evaluation import GoldenDataset
from rag_db.services.database import get_session_factory
from rag_shared.config import get_settings
from sqlalchemy import select


async def _move(apply: bool) -> int:
    settings = get_settings()
    target_bucket = resolve_bucket(settings)
    with get_session_factory(settings)() as db:
        rows = list(
            db.scalars(
                select(GoldenDataset).where(
                    GoldenDataset.storage_key.is_not(None), GoldenDataset.storage_bucket.is_not(None)
                )
            )
        )
        stale = [row for row in rows if row.storage_bucket != target_bucket]
        print(f"{len(rows)} dataset file(s), {len(stale)} outside {target_bucket}.")
        if not stale or not apply:
            for row in stale:
                print(f"  would move {row.storage_bucket}/{row.storage_key}")
            return 0

        moved = missing = 0
        for row in stale:
            old_bucket, old_key = row.storage_bucket, row.storage_key
            try:
                data = await get_dataset(settings, bucket=old_bucket, key=old_key)
            except DatasetStorageError as exc:
                # Nothing to move: the object is already gone, so nothing is ingested either.
                print(f"  skip {old_bucket}/{old_key}: {exc}")
                missing += 1
                continue
            await put_dataset(
                settings, bucket=target_bucket, key=old_key, data=data, filename=old_key
            )
            row.storage_bucket = target_bucket
            db.commit()
            await delete_dataset(settings, bucket=old_bucket, key=old_key)
            print(f"  moved {old_bucket}/{old_key} -> {target_bucket}/{old_key}")
            moved += 1

        print(f"moved {moved}, skipped {missing}.")
        if moved:
            print(
                "The ingestion service purges these files from the product destinations on its "
                "next fanout tick, because they left the source bucket."
            )
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="copy, repoint and delete for real")
    raise SystemExit(asyncio.run(_move(parser.parse_args().apply)))
