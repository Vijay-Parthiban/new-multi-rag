"""The dense client must not send more inputs than the model accepts."""
from __future__ import annotations

from types import SimpleNamespace

from platform_common.embeddings.dense import _MAX_EMBED_BATCH, EmbeddingClient


class _RecordingEmbeddings:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def create(self, *, model: str, input: list[str], extra_body: dict) -> SimpleNamespace:
        self.batch_sizes.append(len(input))
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.0, 1.0]) for _ in input])


def _client_with(fake: _RecordingEmbeddings) -> EmbeddingClient:
    client = object.__new__(EmbeddingClient)
    client._client = SimpleNamespace(embeddings=fake)
    client._model = "test-model"
    return client


def test_splits_a_large_batch() -> None:
    fake = _RecordingEmbeddings()
    client = _client_with(fake)

    vectors = client.embed_passages([f"chunk {i}" for i in range(600)])

    assert len(vectors) == 600
    assert fake.batch_sizes == [_MAX_EMBED_BATCH, _MAX_EMBED_BATCH, 600 - 2 * _MAX_EMBED_BATCH]


def test_one_small_batch_stays_one_request() -> None:
    fake = _RecordingEmbeddings()
    client = _client_with(fake)

    assert len(client.embed_passages(["a", "b"])) == 2
    assert fake.batch_sizes == [2]
