from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

WEB_SCRAPE_SOURCE_TYPE = "web_scrape"
FILE_INGEST_SOURCE_TYPE = "file_ingest"

SourceTypeFilter = Literal["all", "web_scrape", "file_ingest"]


class SourceType(StrEnum):
    WEB_SCRAPE = "web_scrape"
    FILE_INGEST = "file_ingest"


class SearchMode(StrEnum):
    HYBRID = "hybrid"
    DENSE = "dense"
    SPARSE = "sparse"


class ChunkPayload(BaseModel):
    source_type: str
    source_id: str
    source_locator: str
    type: str
    content: str
    chunk_index: int
    title: str | None = None
    scrape_job_id: str | None = None
    url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KpStores(BaseModel):
    """The knowledge-product store names one assistant strategy reads.

    Lives here rather than in rag-core so both rag-core and retrieval-core can
    name it without an import cycle.
    """

    qdrant_collection: str | None = None
    opensearch_index: str | None = None
    pg_schema: str | None = None
    pg_table: str | None = None


class KpStrategy(StrEnum):
    """The RAG strategy an assistant pipeline runs.

    Two kinds live here. Vector, lexical and hybrid are **retrieval modes**: each
    names the store to read. Self-reflective and corrective are **generation
    patterns**: they wrap whichever retrieval mode the product can serve and add a
    grading step before the answer is written. These are separate from the
    ingestion-side ``RagStrategy``, which names the index shape to write.

    RELATIONAL is retained for rows written before SQL search was retired. It is no
    longer offered and no longer reachable.
    """

    VECTOR = "vector"
    LEXICAL = "lexical"
    RELATIONAL = "relational"
    HYBRID = "hybrid"
    SELF_RAG = "self_rag"
    CORRECTIVE = "corrective"


# The generation patterns. Each needs a retrieval mode underneath, so a product
# serves one only when it serves at least one retrieval mode.
AGENTIC_STRATEGIES: tuple[str, ...] = (KpStrategy.SELF_RAG, KpStrategy.CORRECTIVE)


class KpDestination(StrEnum):
    """The ingestion destinations an assistant can read chunks from."""

    VECTOR = "vector_qdrant"
    LEXICAL = "lexical_opensearch"
    RELATIONAL = "relational_pgvector"


class RetrievedChunk(BaseModel):
    id: str
    content: str
    source_type: str
    source_id: str
    source_locator: str
    chunk_index: int
    chunk_type: str
    title: str | None = None
    retrieval_score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class RerankedChunk(RetrievedChunk):
    rerank_score: float
