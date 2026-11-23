"""Queue + TaskGroup crawler with bounded, polite concurrent requests."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Callable, Iterable
from urllib.parse import urlsplit

import httpx

from .fetch import USER_AGENT, FetchResult, fetch
from .parse import PageParser, canonicalize
from .robots import RobotsCache

LOG = logging.getLogger('findex.crawl')


@dataclass(frozen=True, slots=True)
class Page:
    url: str
    title: str
    text: str
    fetched_at: str


@dataclass(slots=True)
class CrawlStats:
    fetched: int = 0
    errors: int = 0
    in_flight: int = 0
    queue_depth: int = 0
    started: float = 0.0


class HostPacer:
    """Exclusive host slot and delay between request START times."""
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.lock = asyncio.Lock()
        self.next_start = 0.0

    async def wait_turn(self) -> None:
        async with self.lock:
            pause = self.next_start - time.monotonic()
            if pause > 0:
                await asyncio.sleep(pause)
            self.next_start = time.monotonic() + self.delay


def domain_allowed(url: str, domains: set[str]) -> bool:
    host = (urlsplit(url).hostname or '').lower()
    return host in domains


async def crawl(
    seeds: Iterable[str], *, max_pages: int = 500, concurrency: int = 10,
    per_host: int = 2, allowed_domains: Iterable[str] | None = None,
    delay: float = 0.2, timeout: float = 10.0,
    client: httpx.AsyncClient | None = None,
    status_callback: Callable[[FetchResult], None] | None = None,
    stats: CrawlStats | None = None,
) -> AsyncIterator[Page]:
    """Yield fetched pages without buffering their contents as a list.

    The page budget counts attempted requests, including failures. robots.txt
    requests are excluded. Client may be injected for offline MockTransport tests.
    """
    if max_pages < 0 or concurrency < 1 or per_host < 1 or delay < 0 or timeout <= 0:
        raise ValueError('Invalid crawler limits')
    seeds = [canonicalize(s) for s in seeds]
    domains = {d.lower() for d in allowed_domains} if allowed_domains is not None else {
        urlsplit(s).hostname or '' for s in seeds
    }
    if not domains or not all(domain_allowed(s, domains) for s in seeds):
        raise ValueError('Seeds must belong to allowed domains')
    if max_pages == 0:
        return

    frontier: asyncio.Queue[str | None] = asyncio.Queue()
    results: asyncio.Queue[Page | None] = asyncio.Queue(maxsize=max(1, concurrency * 2))
    seen: set[str] = set()
    reserved = 0
    host_semaphores: dict[str, asyncio.Semaphore] = {}
    pacers: dict[str, HostPacer] = {}
    global_sem = asyncio.Semaphore(concurrency)
    state = stats or CrawlStats()
    state.started = time.monotonic()
    state.fetched = state.errors = state.in_flight = state.queue_depth = 0

    def schedule(url: str) -> None:
        nonlocal reserved
        if url not in seen and domain_allowed(url, domains) and reserved < max_pages:
            seen.add(url)
            reserved += 1
            frontier.put_nowait(url)
            state.queue_depth = frontier.qsize()

    for seed in seeds:
        schedule(seed)

    async def run(active_client: httpx.AsyncClient) -> AsyncIterator[Page]:
        robots = RobotsCache(active_client)

        async def worker() -> None:
            while True:
                url = await frontier.get()
                try:
                    if url is None:
                        return
                    host = urlsplit(url).netloc
                    sem = host_semaphores.setdefault(host, asyncio.Semaphore(per_host))
                    pacer = pacers.setdefault(host, HostPacer(delay))
                    state.queue_depth = frontier.qsize()
                    if not await robots.allowed(url):
                        state.errors += 1
                        record = FetchResult(url, None, b'', 0.0, 0, 'robots.txt disallows or unavailable')
                        if status_callback:
                            status_callback(record)
                        continue
                    async with global_sem, sem:
                        await pacer.wait_turn()
                        state.in_flight += 1
                        try:
                            record = await fetch(active_client, url, timeout=timeout)
                        finally:
                            state.in_flight -= 1
                    if status_callback:
                        status_callback(record)
                    if not record.ok or 'html' not in record.content_type.lower():
                        state.errors += 1
                        continue
                    parser = PageParser()
                    # HTML extraction is intentionally bounded by fetch body size in real use;
                    # for typical HTML pages it is short. CPU-heavy indexing is elsewhere.
                    parser.feed(record.body.decode('utf-8', errors='replace'))
                    title, body, links = parser.extract(url)
                    # Redirects are not followed: avoids crossing allowed-domain boundary.
                    for link in links:
                        schedule(link)
                    state.fetched += 1
                    await results.put(Page(url, title, body, datetime.now(timezone.utc).isoformat()))
                except Exception as exc:
                    state.errors += 1
                    LOG.warning('worker failed on %s: %s', url, exc)
                finally:
                    frontier.task_done()

        async def coordinator() -> None:
            await frontier.join()
            for _ in range(concurrency):
                frontier.put_nowait(None)
            await results.put(None)

        async with asyncio.TaskGroup() as group:
            workers = [group.create_task(worker()) for _ in range(concurrency)]
            finish = group.create_task(coordinator())
            try:
                while True:
                    item = await results.get()
                    if item is None:
                        break
                    yield item
            finally:
                finish.cancel()
                for task in workers:
                    task.cancel()

    if client is None:
        async with httpx.AsyncClient(headers={'User-Agent': USER_AGENT}, max_redirects=5) as active:
            async for page in run(active):
                yield page
    else:
        # Reuse injected client for MockTransport tests; never close caller's client.
        async for page in run(client):
            yield page


def page_json(page: Page) -> str:
    return json.dumps(asdict(page), ensure_ascii=False)
