"""Linear two-pointer Boolean posting merges and backward-compatible search CLI."""

import argparse
import time
import tracemalloc
from pathlib import Path
from typing import Sequence

from findex.index import Engine, Index
from findex.query import parse
from findex.store import load


def merge_and(left: Sequence[int], right: Sequence[int]) -> list[int]:
    i, j, result = 0, 0, []
    while i < len(left) and j < len(right):
        if left[i] == right[j]:
            result.append(left[i])
            i += 1
            j += 1
        elif left[i] < right[j]:
            i += 1
        else:
            j += 1
    return result


def merge_or(left: Sequence[int], right: Sequence[int]) -> list[int]:
    i, j, result = 0, 0, []
    while i < len(left) or j < len(right):
        if i == len(left):
            value = right[j]
            j += 1
        elif j == len(right):
            value = left[i]
            i += 1
        elif left[i] < right[j]:
            value = left[i]
            i += 1
        elif right[j] < left[i]:
            value = right[j]
            j += 1
        else:
            value = left[i]
            i += 1
            j += 1
        if not result or result[-1] != value:
            result.append(value)
    return result


def merge_not(universe: Sequence[int], excluded: Sequence[int]) -> list[int]:
    i, j, result = 0, 0, []
    while i < len(universe):
        if j == len(excluded) or universe[i] < excluded[j]:
            result.append(universe[i])
            i += 1
        elif universe[i] == excluded[j]:
            i += 1
            j += 1
        else:
            j += 1
    return result


def boolean_search(index: Index, query: str, engine: Engine = "merge") -> list[int]:
    if engine not in ("merge", "set"):
        raise ValueError("engine must be 'merge' or 'set'")
    return sorted(parse(query).evaluate(index, engine))


def main() -> None:
    parser = argparse.ArgumentParser(description="Boolean search a saved findex index")
    parser.add_argument("index", type=Path)
    parser.add_argument("query")
    parser.add_argument("--engine", choices=["merge", "set"], default="merge")
    args = parser.parse_args()
    tracemalloc.start()
    start = time.perf_counter()
    try:
        ix = load(args.index)
        engine: Engine = "set" if args.engine == "set" else "merge"
        ids = boolean_search(ix, args.query, engine)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    for doc_id in ids:
        print(f"{doc_id}\t{ix.doc_meta[doc_id].title}")
    print(f"{len(ids)} results; {time.perf_counter()-start:.4f}s; peak {peak/1048576:.3f} MiB")


if __name__ == "__main__":
    main()
