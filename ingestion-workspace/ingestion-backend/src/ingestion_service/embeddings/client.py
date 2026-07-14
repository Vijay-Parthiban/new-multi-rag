import base64
import logging

from openai import OpenAI

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """LiteLLM-compatible embedding client (text + image)."""

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self._client = OpenAI(base_url=base_url.rstrip("/"), api_key=api_key)
        self._model = model

    def embed_passage(self, text: str) -> list[float]:
        text = text.strip()
        if not text:
            raise ValueError("Cannot embed empty text")
            
        if len(text) > 16000:
            text = text[:16000]
            
        response = self._client.embeddings.create(
            model=self._model,
            input=[text],
            extra_body={"input_type": "passage", "truncate": "END"},
        )
        return response.data[0].embedding

    def embed_image_png(self, image_bytes: bytes) -> list[float]:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:image/png;base64,{encoded}"
        response = self._client.embeddings.create(
            model=self._model,
            input=[data_url],
            extra_body={"input_type": "passage", "truncate": "END"},
        )
        return response.data[0].embedding

    @staticmethod
    def image_to_data_uri(image_bytes: bytes) -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:image/png;base64,{encoded}"
