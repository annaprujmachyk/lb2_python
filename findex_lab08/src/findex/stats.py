"""Command-line corpus statistics and eager/lazy benchmark.

Usage:
    python -m findex.stats data/
    python -m findex.stats data/ --limit 20
    python -m findex.stats data/ --compare
"""

import argparse
import logging
import time
import tracemalloc
from collections import Counter
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Callable

from findex.corpus import iter_documents
from findex.tokenize import tokenize


@dataclass
class Stats:
    documents: int
    tokens: int
    frequencies: Counter[str]

    @property
    def vocabulary(self) -> int:
        return len(self.frequencies)


def lazy_stats(root: Path, limit: int | None = None) -> Stats:
    docs = iter_documents(root)
    if limit is not None:
        docs = islice(docs, limit)

    counts: Counter[str] = Counter()
    doc_count = 0
    token_count = 0
    for doc in docs:
        doc_count += 1
        for token in tokenize(doc.text):
            counts[token] += 1
            token_count += 1
    return Stats(doc_count, token_count, counts)


def eager_stats(root: Path, limit: int | None = None) -> Stats:
    """Deliberately materialize documents AND token lists for comparison."""
    documents = (
        list(islice(iter_documents(root), limit))
        if limit is not None
        else list(iter_documents(root))
    )
    token_lists = [list(tokenize(document.text)) for document in documents]
    counts = Counter(token for tokens in token_lists for token in tokens)
    return Stats(len(documents), sum(map(len, token_lists)), counts)


def measure(action: Callable[[], Stats]) -> tuple[Stats, float, int]:
    """Return statistics, elapsed seconds and peak Python-allocated memory bytes."""
    tracemalloc.start()
    try:
        start = time.perf_counter()
        result = action()
        elapsed = time.perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return result, elapsed, peak


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a text corpus lazily")
    parser.add_argument("root", type=Path, help="Directory of .txt documents")
    parser.add_argument("--limit", type=int, default=None, help="First N documents")
    parser.add_argument("--compare", action="store_true", help="Benchmark eager vs lazy")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be nonnegative")
    if not args.root.is_dir():
        parser.error(f"Not a directory: {args.root}")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    results, elapsed, peak = measure(lambda: lazy_stats(args.root, args.limit))
    print(f"Documents: {results.documents}")
    print(f"Tokens: {results.tokens}")
    print(f"Vocabulary: {results.vocabulary}")
    print("Top 50 terms:")
    for term, count in results.frequencies.most_common(50):
        print(f"  {term}: {count}")
    print(f"Elapsed: {elapsed:.4f} s")
    print(f"Peak traced memory: {peak / 1024**2:.3f} MiB")

    if args.compare:
        eager, eager_seconds, eager_peak = measure(
            lambda: eager_stats(args.root, args.limit)
        )
        assert results.documents == eager.documents
        assert results.tokens == eager.tokens
        assert results.frequencies == eager.frequencies
        print("\n| Version | Documents | Peak memory (MiB) | Elapsed (s) |")
        print("|---|---:|---:|---:|")
        print(
            f"| eager (lists) | {eager.documents} | "
            f"{eager_peak / 1024**2:.3f} | {eager_seconds:.4f} |"
        )
        print(
            f"| lazy (generators) | {results.documents} | "
            f"{peak / 1024**2:.3f} | {elapsed:.4f} |"
        )


if __name__ == "__main__":
    main()
