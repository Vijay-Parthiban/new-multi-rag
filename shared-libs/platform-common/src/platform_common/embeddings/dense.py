"""LiteLLM-compatible dense embedding client (text + image)."""
from __future__ import annotations

import base64
import logging

from openai import OpenAI

logger = logging.getLogger(__name__)

_MAX_EMBED_CHARS = 16_000


class EmbeddingClient:
    """OpenAI SDK client pointed at a LiteLLM proxy for text or multimodal embeddings."""

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self._client = OpenAI(base_url=base_url.rstrip("/"), api_key=api_key)
        self._model = model

    def embed_passage(self, text: str) -> list[float]:
        text = text.strip()
        if not text:
            raise ValueError("Cannot embed empty text")
        if len(text) > _MAX_EMBED_CHARS:
            text = text[:_MAX_EMBED_CHARS]
        response = self._client.embeddings.create(
            model=self._model,
            input=[text],
            extra_body={"input_type": "passage", "truncate": "END"},
        )
        vector = response.data[0].embedding
        logger.info(
            "embedding_created source=passage model=%s dimensions=%d",
            self._model,
            len(vector),
        )
        return vector

    def embed_text(self, text: str) -> list[float]:
        """Embed a query string (input_type=query). Truncates very long inputs."""
        text = text.strip()
        if not text:
            raise ValueError("Cannot embed empty text")
        if len(text) > _MAX_EMBED_CHARS:
            text = text[:_MAX_EMBED_CHARS]
        response = self._client.embeddings.create(
            model=self._model,
            input=[text],
            extra_body={"input_type": "query", "truncate": "END"},
        )
        vector = response.data[0].embedding
        logger.info(
            "embedding_created source=query model=%s dimensions=%d",
            self._model,
            len(vector),
        )
        return vector

    def embed_image_png(self, image_bytes: bytes) -> list[float]:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:image/png;base64,{encoded}"
        response = self._client.embeddings.create(
            model=self._model,
            input=[data_url],
            extra_body={"input_type": "passage", "truncate": "END"},
        )
        vector = response.data[0].embedding
        logger.info(
            "embedding_created source=image model=%s dimensions=%d",
            self._model,
            len(vector),
        )
        return vector

    @staticmethod
    def image_to_base64(image_bytes: bytes) -> str:
        return base64.b64encode(image_bytes).decode("ascii")

    @staticmethod
    def image_to_data_uri(image_bytes: bytes) -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:image/png;base64,{encoded}"
