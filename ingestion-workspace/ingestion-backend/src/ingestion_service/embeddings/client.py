"""Dense embedding client with LiteLLM proxy and FastEmbed fallback."""
import base64
import logging
from typing import Any

from platform_common.embeddings import EmbeddingClient as BaseEmbeddingClient

logger = logging.getLogger(__name__)

_FASTEMBED_MODEL = None


def _get_fastembed_model():
    global _FASTEMBED_MODEL
    if _FASTEMBED_MODEL is None:
        from fastembed import TextEmbedding
        _FASTEMBED_MODEL = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    return _FASTEMBED_MODEL


class EmbeddingClient:
    """Wrapper that tries LiteLLM proxy first and falls back to FastEmbed if unreachable."""

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self._base_client = BaseEmbeddingClient(base_url=base_url, api_key=api_key, model=model)
        self._model = model

    @classmethod
    def image_to_data_uri(cls, image_bytes: bytes) -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def embed_passage(self, text: str) -> list[float]:
        try:
            return self._base_client.embed_passage(text)
        except Exception as exc:
            logger.warning("LiteLLM embedding failed, falling back to FastEmbed: %s", exc)
            return self._embed_fastembed(text)

    def embed_text(self, text: str) -> list[float]:
        try:
            return self._base_client.embed_text(text)
        except Exception as exc:
            logger.warning("LiteLLM embedding failed, falling back to FastEmbed: %s", exc)
            return self._embed_fastembed(text)

    def embed_image_png(self, image_bytes: bytes) -> list[float]:
        try:
            return self._base_client.embed_image_png(image_bytes)
        except Exception as exc:
            logger.warning("LiteLLM image embedding failed: %s", exc)
            return [0.0] * 384

    def _embed_fastembed(self, text: str) -> list[float]:
        text = text.strip()
        if not text:
            raise ValueError("Cannot embed empty text")
        fe = _get_fastembed_model()
        embeddings = list(fe.embed([text]))
        if embeddings and len(embeddings) > 0:
            return list(map(float, embeddings[0]))
        return [0.0] * 384


__all__ = ["EmbeddingClient"]
