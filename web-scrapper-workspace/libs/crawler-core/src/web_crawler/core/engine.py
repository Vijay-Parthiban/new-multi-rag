from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed

import httpx

from crawler_shared.types import DiscoveredLink
from platform_common.ssrf import validate_public_http_url
from web_crawler.core.frontier import FrontierItem
from web_crawler.core.frontier import CrawlFrontier
from web_crawler.core.link_extractor import FetchMode
from web_crawler.core.link_extractor import LinkExtractor
from web_crawler.utils.url import is_same_domain

logger = logging.getLogger(__name__)


class CrawlerEngine:
    def __init__(
        self,
        *,
        max_depth: int,
        max_pages: int,
        client: httpx.Client | None = None,
        same_domain_only: bool = True,
        min_result_depth: int = 0,
        max_result_depth: int | None = None,
        fetch_mode: FetchMode = "httpx",
        playwright_timeout_ms: int = 15000,
        max_workers: int = 4,
    ) -> None:
        """Create a crawler engine.

        The engine traverses pages breadth-first (via `CrawlFrontier`) up to `max_pages`
        and only expands children up to `max_depth`.

        Results:
        - The returned `DiscoveredLink` list contains every fetched URL (subject to
          `min_result_depth`/`max_result_depth`), so the links file reflects what
          was actually crawled.
        """
        if max_depth < 0:
            raise ValueError("max_depth must be >= 0")
        if max_pages < 1:
            raise ValueError("max_pages must be >= 1")
        if min_result_depth < 0:
            raise ValueError("min_result_depth must be >= 0")
        if max_result_depth is not None and max_result_depth < 0:
            raise ValueError("max_result_depth must be >= 0")
        if max_result_depth is not None and min_result_depth > max_result_depth:
            raise ValueError("min_result_depth must be <= max_result_depth")
        if fetch_mode not in {"httpx", "playwright", "auto"}:
            raise ValueError("fetch_mode must be one of: httpx, playwright, auto")
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self._max_depth = max_depth
        self._max_pages = max_pages
        self._same_domain_only = same_domain_only
        self._min_result_depth = min_result_depth
        self._max_result_depth = max_result_depth
        self._max_workers = max_workers
        self._client = client or httpx.Client(headers={"User-Agent": "web-crawler/0.1"})
        self._owns_client = client is None
        self._extractor = LinkExtractor(
            self._client,
            fetch_mode=fetch_mode,
            playwright_timeout_ms=playwright_timeout_ms,
        )

    def crawl(self, seed_url: str) -> list[DiscoveredLink]:
        """Crawl from `seed_url` and return fetched pages as `DiscoveredLink` records.

        The crawl stops when either:
        - the frontier is empty (no more URLs to visit), or
        - `max_pages` pages have been fetched.
        """
        started = time.perf_counter()
        seed = self._extractor.normalize(seed_url)
        allow_private = os.getenv("ALLOW_PRIVATE_CRAWL_URLS", "").lower() in {
            "1",
            "true",
            "yes",
        }
        seed = validate_public_http_url(seed, allow_private=allow_private)
        logger.info(
            "crawl_start seed=%s max_depth=%d max_pages=%d mode=%s workers=%d same_domain_only=%s",
            seed,
            self._max_depth,
            self._max_pages,
            getattr(self._extractor, "_fetch_mode", "httpx"),
            self._max_workers,
            self._same_domain_only,
        )
        frontier = CrawlFrontier()
        frontier.push(seed, 0, None)
        visited: set[str] = set()
        discovered: list[DiscoveredLink] = []
        pages_crawled = 0

        try:
            with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
                while frontier and pages_crawled < self._max_pages:
                    remaining = self._max_pages - pages_crawled
                    batch = self._collect_batch(frontier, visited, remaining)
                    if not batch:
                        continue

                    for item, status_code, child_links in self._crawl_batch(executor, batch):
                        include_in_results = self._include_depth(item.depth)
                        if include_in_results:
                            discovered.append(
                                DiscoveredLink(
                                    url=item.url,
                                    depth=item.depth,
                                    parent=item.parent,
                                    status_code=status_code,
                                )
                            )
                        pages_crawled += 1
                        logger.debug(
                            "page_fetched url=%s depth=%d status=%s extracted_links=%d include=%s",
                            item.url,
                            item.depth,
                            status_code,
                            len(child_links),
                            include_in_results,
                        )

                        if item.depth >= self._max_depth:
                            continue

                        for link in child_links:
                            if link in visited:
                                continue
                            if self._same_domain_only and not is_same_domain(seed, link):
                                continue
                            frontier.push(link, item.depth + 1, item.url)
        finally:
            self._extractor.close()
            if self._owns_client:
                self._client.close()

        duration_ms = int((time.perf_counter() - started) * 1000)
        self.last_metadata = {
            "duration_ms": duration_ms,
            "pages_crawled": pages_crawled,
            "seed_url": seed,
        }
        logger.info(
            "crawl_done seed=%s pages_crawled=%d results=%d duration_ms=%d",
            seed,
            pages_crawled,
            len(discovered),
            duration_ms,
        )
        return discovered

    @property
    def pages_crawled(self) -> int:
        """Pages fetched in the most recent `crawl()` run."""
        metadata = getattr(self, "last_metadata", None)
        if metadata is None:
            return 0
        return int(metadata.get("pages_crawled", 0))

    def _include_depth(self, depth: int) -> bool:
        """Apply the result-depth filter (min/max) for returned links."""
        if depth < self._min_result_depth:
            return False
        if self._max_result_depth is not None and depth > self._max_result_depth:
            return False
        return True

    def _collect_batch(
        self,
        frontier: CrawlFrontier,
        visited: set[str],
        remaining: int,
    ) -> list[FrontierItem]:
        """Pop up to N unique URLs from the frontier to fetch in parallel."""
        batch_size = min(self._max_workers, remaining)
        batch: list[FrontierItem] = []
        while frontier and len(batch) < batch_size:
            item = frontier.pop()
            assert item is not None
            if item.url in visited:
                continue
            visited.add(item.url)
            batch.append(item)
        return batch

    def _crawl_batch(
        self,
        executor: ThreadPoolExecutor,
        batch: list[FrontierItem],
    ) -> list[tuple[FrontierItem, int | None, list[str]]]:
        """Fetch a batch of URLs, returning (item, status, extracted_links) for each."""
        if len(batch) == 1:
            return [self._crawl_one(batch[0])]
        futures = [executor.submit(self._crawl_one, item) for item in batch]
        return [future.result() for future in as_completed(futures)]

    def _crawl_one(self, item: FrontierItem) -> tuple[FrontierItem, int | None, list[str]]:
        """Fetch one URL and extract its outgoing links."""
        html, status_code = self._extractor.fetch(item.url)
        if html is None:
            return item, status_code, []
        child_links = self._extractor.extract(html, item.url)
        return item, status_code, child_links
