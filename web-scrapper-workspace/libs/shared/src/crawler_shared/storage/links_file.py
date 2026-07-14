import json
from collections.abc import Iterator
import logging
from pathlib import Path
from uuid import UUID

from crawler_shared.types import DiscoveredLink

logger = logging.getLogger(__name__)


class LinksFileWriter:
    def __init__(self, base_dir: Path) -> None:
        """Write/read newline-delimited JSON link files.

        Why JSONL:
        - append/stream friendly
        - one record per line makes partial reads easy
        - avoids storing massive URL lists row-by-row in the DB
        """
        self._base_dir = base_dir

    def write(self, job_id: UUID | str, links: list[DiscoveredLink]) -> Path:
        """Write links to `base_dir/<job_id>/links.jsonl` and return the path."""
        job_dir = self._base_dir / str(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        path = job_dir / "links.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for link in links:
                record = {
                    "url": link.url,
                    "depth": link.depth,
                    "parent": link.parent,
                    "status_code": link.status_code,
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info("links_file_written job_id=%s path=%s count=%d", str(job_id), str(path), len(links))
        return path

    @staticmethod
    def read(path: Path | str) -> Iterator[DiscoveredLink]:
        """Read a JSONL links file and yield `DiscoveredLink` records."""
        file_path = Path(path)
        with file_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                yield DiscoveredLink(
                    url=record["url"],
                    depth=record["depth"],
                    parent=record.get("parent"),
                    status_code=record.get("status_code"),
                )
