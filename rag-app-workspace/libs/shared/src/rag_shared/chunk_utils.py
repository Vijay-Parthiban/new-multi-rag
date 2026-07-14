from __future__ import annotations

from rag_shared.types import RerankedChunk, RetrievedChunk

ChunkLike = RetrievedChunk | RerankedChunk


def is_image_chunk(chunk: ChunkLike) -> bool:
    if chunk.chunk_type == "image":
        return True
    content = chunk.content.strip()
    return content.startswith("data:image/")


def image_data_uri(chunk: ChunkLike) -> str | None:
    content = chunk.content.strip()
    if content.startswith("data:image/"):
        return content
    image_from_meta = chunk.metadata.get("image_base64") or chunk.metadata.get("image")
    if isinstance(image_from_meta, str) and image_from_meta.strip():
        value = image_from_meta.strip()
        if value.startswith("data:image/"):
            return value
        mime = chunk.metadata.get("mime_type", "image/png")
        return f"data:{mime};base64,{value}"
    return None


def passage_text_for_chunk(chunk: ChunkLike) -> str:
    if is_image_chunk(chunk):
        return chunk.title or chunk.source_locator or f"Image chunk {chunk.chunk_index}"
    return chunk.content


def split_chunks(chunks: list[ChunkLike]) -> tuple[list[ChunkLike], list[ChunkLike]]:
    text_chunks: list[ChunkLike] = []
    image_chunks: list[ChunkLike] = []
    for chunk in chunks:
        if is_image_chunk(chunk):
            image_chunks.append(chunk)
        else:
            text_chunks.append(chunk)
    return text_chunks, image_chunks
