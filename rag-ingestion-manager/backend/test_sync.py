
import asyncio
import logging
import uuid
from src.ingestion_service.core.pathway_sync import sync_source_from_pathway
from src.shared.db.session import AsyncSessionLocal

logging.basicConfig(level=logging.DEBUG)

async def test():
    async with AsyncSessionLocal() as db:
        await sync_source_from_pathway(db, uuid.UUID('d9aa52ff-8019-4952-8130-00a9f1174b2d'))

asyncio.run(test())
