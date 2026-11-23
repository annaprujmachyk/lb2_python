"""Offline permitted 220-page simulated site; deterministic network latency."""
from __future__ import annotations
import asyncio
import csv
import json
import sys
import time
from pathlib import Path

import httpx
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from findex.crawler.crawl import CrawlStats, crawl

N = 220


async def run_one(concurrency: int) -> dict:
    async def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == '/robots.txt':
            return httpx.Response(200, text='User-agent: *\nAllow: /\n')
        await asyncio.sleep(0.012)  # simulation: network waiting, not CPU
        i = int(req.url.path.strip('/') or '0')
        link = f'<a href="/{i+1}">Next</a>' if i + 1 < N else ''
        # Expose all links to make concurrency meaningful.
        if i == 0:
            link = ''.join(f'<a href="/{j}">page</a>' for j in range(1, N))
        return httpx.Response(200, text=f'<html><title>Page {i}</title><body>text {i}{link}</body></html>', headers={'content-type': 'text/html'})

    stats = CrawlStats()
    process = psutil.Process()
    peak = process.memory_info().rss
    start = time.perf_counter()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        count = 0
        async for _ in crawl(['https://owned.local/0'], max_pages=N, concurrency=concurrency,
                             per_host=20, delay=0, client=client, stats=stats):
            count += 1
            peak = max(peak, process.memory_info().rss)
    wall = time.perf_counter()-start
    return {'concurrency': concurrency, 'pages': count, 'wall_s': round(wall, 3),
            'pages_per_s': round(count/wall, 2), 'errors': stats.errors,
            'peak_rss_mib': round(peak/1024**2, 2)}


async def main():
    rows = [await run_one(n) for n in [1, 5, 20]]
    root = Path(__file__).resolve().parents[1]
    (root / 'LAB06_BENCHMARK.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    with (root / 'LAB06_BENCHMARK.csv').open('w', newline='') as f:
        w=csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    for row in rows:
        print(row)

if __name__ == '__main__':
    asyncio.run(main(), debug=True)
