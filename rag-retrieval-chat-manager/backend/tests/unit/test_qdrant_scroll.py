from __future__ import annotations

from types import SimpleNamespace

from vector_core.qdrant_store import QdrantStore


class _Page:
    def __init__(self, payloads: list[dict]) -> None:
        self._payloads = payloads

    def __iter__(self):
        return iter([SimpleNamespace(payload=p) for p in self._payloads])


class _FakeClient:
    def __init__(self, pages: list[list[dict]], next_offsets: list[object]) -> None:
        self.pages = pages
        self.next_offsets = next_offsets
        self.calls: list[dict] = []

    def scroll(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        return _Page(self.pages[index]), self.next_offsets[index]


def _store_with(client: _FakeClient) -> QdrantStore:
    store = QdrantStore.__new__(QdrantStore)
    store._store = SimpleNamespace(client=client, collection="kp")
    return store


def test_scroll_payloads_concatenates_pages_in_order_and_stops_at_limit():
    client = _FakeClient(
        pages=[[{"id": 1}, {"id": 2}], [{"id": 3}]],
        next_offsets=["cursor-1", None],
    )

    payloads = _store_with(client).scroll_payloads(limit=3)

    assert payloads == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert len(client.calls) == 2
    assert client.calls[0]["collection_name"] == "kp"
    assert client.calls[0]["offset"] is None
    assert client.calls[0]["with_payload"] is True
    assert client.calls[0]["with_vectors"] is False
    assert client.calls[1]["offset"] == "cursor-1"
    assert client.calls[1]["limit"] == 1


def test_scroll_payloads_stops_when_the_store_returns_no_cursor():
    client = _FakeClient(pages=[[{"id": 1}]], next_offsets=[None])
    assert _store_with(client).scroll_payloads(limit=100) == [{"id": 1}]
    assert len(client.calls) == 1
