"""The page-image embedder must fail loudly.

A zero vector of a guessed length would be stored as if it described the page, and
a wrong length poisons the collection it lands in. A failure has to reach the
per-file error path instead.
"""

import pytest

from src.ingestion_service.embeddings.client import EmbeddingClient


def test_embed_image_png_raises_when_the_model_cannot_answer() -> None:
    # Port 1 has no listener, so the proxy call fails at connect time.
    client = EmbeddingClient(
        base_url="http://127.0.0.1:1/v1", api_key="unused", model="nvidia-embed-multimodal"
    )

    with pytest.raises(Exception):
        client.embed_image_png(b"\x89PNG\r\n\x1a\n" + b"page bytes")
