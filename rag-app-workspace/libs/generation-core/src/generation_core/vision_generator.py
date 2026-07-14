from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI
from generation_core.prompt_builder import NO_SOURCES_ANSWER
from rag_shared.chunk_utils import image_data_uri, passage_text_for_chunk
from rag_shared.types import RerankedChunk

logger = logging.getLogger(__name__)


class VisionGenerator:
    """Vision LLM via LiteLLM proxy. Uses image data URIs already stored on Qdrant chunks."""

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self._client = OpenAI(base_url=base_url.rstrip("/"), api_key=api_key)
        self._default_model = model

    def generate(
        self,
        query: str,
        chunks: list[RerankedChunk],
        *,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str:
        if not chunks:
            return NO_SOURCES_ANSWER

        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Answer the question using ONLY the screenshot context below. "
                    "Describe only what is visible or inferable from the images. "
                    "If no images are provided or they do not contain information "
                    "relevant to the question, say clearly that you could not find "
                    "relevant sources to answer the question. Do not guess.\n\n"
                    f"Question: {query}"
                ),
            }
        ]

        image_count = 0
        for index, chunk in enumerate(chunks, start=1):
            data_uri = image_data_uri(chunk)
            if not data_uri:
                logger.warning("skipping_image_chunk_without_uri chunk_id=%s", chunk.id)
                continue

            image_count += 1
            locator = chunk.source_locator or "unknown"
            caption = passage_text_for_chunk(chunk)
            content.append({"type": "text", "text": f"[Image {index}] Source: {locator}\n{caption}"})
            content.append({"type": "image_url", "image_url": {"url": data_uri}})

        if image_count == 0:
            return NO_SOURCES_ANSWER

        response = self._client.chat.completions.create(
            model=model or self._default_model,
            messages=[{"role": "user", "content": content}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = response.choices[0].message.content or ""
        logger.info(
            "vision_generate_completed model=%s images=%d",
            model or self._default_model,
            len(chunks),
        )
        return text
