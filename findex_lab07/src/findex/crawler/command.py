"""Streaming crawler CLI driver and progress reporting."""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.table import Table

from .crawl import CrawlStats, crawl, page_json
from .fetch import FetchResult


def _display(stats: CrawlStats) -> Table:
    t = Table(title='findex crawler')
    t.add_column('Pages')
    t.add_column('Pages/s')
    t.add_column('In flight')
    t.add_column('Errors')
    t.add_column('Queue')
    seconds = max(0.001, time.monotonic() - stats.started)
    t.add_row(str(stats.fetched), f'{stats.fetched / seconds:.2f}',
              str(stats.in_flight), str(stats.errors), str(stats.queue_depth))
    return t


async def run_crawl(
    seed: str, out: Path, *, max_pages: int = 500,
    concurrency: int = 10, per_host: int = 2, delay: float = 0.2,
    allowed_domains: list[str] | None = None, log_file: Path = Path('crawl.log'),
    console: Console | None = None,
) -> int:
    console = console or Console(stderr=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('findex.crawl.requests')
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)
    state = CrawlStats()

    def on_result(record: FetchResult) -> None:
        logger.info('url=%s status=%s bytes=%d elapsed=%.3f attempts=%d error=%s',
                    record.url, record.status, len(record.body), record.elapsed,
                    record.attempts, record.error or '-')

    count = 0
    try:
        with out.open('w', encoding='utf-8') as writer, Live(_display(state), console=console, refresh_per_second=4, transient=True) as live:
            async for page in crawl([seed], max_pages=max_pages, concurrency=concurrency,
                                    per_host=per_host, delay=delay,
                                    allowed_domains=allowed_domains,
                                    status_callback=on_result, stats=state):
                await asyncio.to_thread(writer.write, page_json(page) + '\n')
                count += 1
                live.update(_display(state))
            live.update(_display(state))
    finally:
        logger.removeHandler(handler)
        handler.close()
    console.print(f'Fetched {count} pages; errors={state.errors}; output={out}; log={log_file}')
    return count
