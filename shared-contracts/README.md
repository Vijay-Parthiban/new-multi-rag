# Shared Contracts

Common Pydantic data models and schemas shared across:
1. `rag-ingestion-manager` (Port 8007)
2. `rag-retrieval-chat-manager` (Port 8001)

## Schemas Included
- **Knowledge Profile Contracts**: `KnowledgeProfileRead`, `KnowledgeProfileCreate`, `KnowledgeDestinationConfigSchema`, `KnowledgeProfileSourceSchema`, `TestConnectionRequest`, `TestConnectionResponse`
- **Data Source Contracts**: `SourceRecordRead`, `SourceSyncStatus`
- **Search & Retrieval Contracts**: `SearchHitContract`, `HybridRetrievalRequest`, `RerankHitContract`
- **RAG Pipeline Contracts**: `PipelineConfigContract`, `RAGTraceContract`
