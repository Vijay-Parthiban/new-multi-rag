from rag_db.sanitize import strip_null_bytes


def test_strip_null_bytes_from_nested_chunk_payload() -> None:
    payload = [
        {
            "id": "1",
            "content": "X \u223cN\n\x00more text",
            "meta": {"title": "ok\x00"},
        }
    ]
    cleaned = strip_null_bytes(payload)
    assert cleaned[0]["content"] == "X \u223cN\nmore text"
    assert cleaned[0]["meta"]["title"] == "ok"
    assert "\x00" not in cleaned[0]["content"]


def test_strip_null_bytes_passthrough_non_strings() -> None:
    assert strip_null_bytes(None) is None
    assert strip_null_bytes(12) == 12
    assert strip_null_bytes(True) is True
