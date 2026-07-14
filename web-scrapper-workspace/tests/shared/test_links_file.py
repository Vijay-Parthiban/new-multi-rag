from pathlib import Path

from crawler_shared.types import DiscoveredLink
from crawler_shared.storage.links_file import LinksFileWriter


def test_links_file_writer_creates_jsonl(tmp_path: Path):
    writer = LinksFileWriter(tmp_path)
    path = writer.write(
        "abc-123",
        [DiscoveredLink(url="https://example.com", depth=0, parent=None, status_code=200)],
    )
    assert path.exists()
    assert path.name == "links.jsonl"
    assert path.parent.name == "abc-123"
