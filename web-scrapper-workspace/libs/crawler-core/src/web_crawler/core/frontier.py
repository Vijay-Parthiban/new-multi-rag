from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class FrontierItem:
    url: str
    depth: int
    parent: str | None


class CrawlFrontier:
    def __init__(self) -> None:
        self._queue: deque[FrontierItem] = deque()

    def push(self, url: str, depth: int, parent: str | None) -> None:
        self._queue.append(FrontierItem(url=url, depth=depth, parent=parent))

    def pop(self) -> FrontierItem | None:
        if not self._queue:
            return None
        return self._queue.popleft()

    def __len__(self) -> int:
        return len(self._queue)

    def __bool__(self) -> bool:
        return bool(self._queue)
