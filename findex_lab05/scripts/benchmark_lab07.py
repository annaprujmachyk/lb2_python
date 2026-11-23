"""Локальний тест: 20 конкурентних HTTP-запитів до sync / async пошуку.

Виконується в пам'яті через ASGITransport, тому це не вимірювання реальної мережі
або Docker та не замінює oha для вимог методички.
"""
from __future__ import annotations

import asyncio
import csv
import statistics
import time
from pathlib import Path

import httpx
from findex.index import build_index
from findex.web.app import Settings, create_app, get_index, query_results


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * p)))]


async def run_mode(mode: str, corpus: Path, count: int = 20):
    ix = build_index(corpus)
    app = create_app(Settings(index_path=Path("missing.json")))
    app.dependency_overrides[get_index] = lambda: ix
    if mode == "async def":
        @app.get("/test-async")
        async def search_async():
            return query_results(ix, "python", 10, "bm25", 1)
        path = "/test-async"
    else:
        path = "/search?q=python"

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async def request():
            start = time.perf_counter()
            response = await client.get(path)
            response.raise_for_status()
            return (time.perf_counter() - start) * 1000
        started = time.perf_counter()
        durations = await asyncio.gather(*(request() for _ in range(count)))
        elapsed = time.perf_counter() - started
    ix.close()
    return {"режим": mode, "запитів": count, "RPS": round(count/elapsed, 2),
            "p50_мс": round(statistics.median(durations), 3),
            "p95_мс": round(pct(durations, .95), 3), "p99_мс": round(pct(durations, .99), 3),
            "загальний_час_с": round(elapsed, 3)}


async def main():
    corpus = Path("data/demo")
    rows = [await run_mode(mode, corpus) for mode in ("def", "async def")]
    with Path("LAB07_LOCAL_BENCHMARK.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(row)


if __name__ == "__main__":
    asyncio.run(main())
