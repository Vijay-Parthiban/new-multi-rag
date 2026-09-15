import asyncio
import logging
import uuid
import sys
import traceback
from src.ingestion_service.core.pathway_sync import _do_sync_source_from_pathway
from src.shared.db.session import AsyncSessionLocal

logging.basicConfig(level=logging.ERROR)

async def test():
    try:
        print("==== STARTING DB SESSION ====")
        async with AsyncSessionLocal() as db:
            await _do_sync_source_from_pathway(db, uuid.UUID('d9aa52ff-8019-4952-8130-00a9f1174b2d'))
            print("==== FINISHED DO SYNC ====")
    except BaseException as e:
        print(f"FAILED WITH EXCEPTION: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
