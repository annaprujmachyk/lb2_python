from __future__ import annotations
"""Streaming, one-pass inverted-index builder and Mapping-based Index API.

Backward-compatible: python -m findex.index CORPUS --out index.json
"""

import argparse
import logging
import time
import tracemalloc
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator, Mapping
from functools import cached_property, lru_cache
from itertools import islice
from pathlib import Path
from uuid import uuid4
from weakref import WeakValueDictionary
from typing import Literal

from findex.corpus import iter_documents
from findex.models import DocMeta, Posting
from findex.timing import timed
from findex.tokenize import tokenize

LOGGER = logging.getLogger(__name__)
Engine = Literal["merge", "set"]
# Cache stores stable, unique instance tokens instead of unhashable Index objects.
_INDEXES: WeakValueDictionary[str, Index] = WeakValueDictionary()


@lru_cache(maxsize=256)
def _cached_query_matches(token: str, query: str, engine: Engine) -> frozenset[int]:
    from findex.query import parse
    index = _INDEXES[token]
    return frozenset(parse(query).evaluate(index, engine))



class Index(Mapping[str, list[Posting]]):
    """Read-only Mapping facade over posting lists, plus document statistics."""

    def __init__(
        self,
        postings: dict[str, list[Posting]],
        doc_lengths: dict[int, int],
        doc_meta: dict[int, DocMeta],
        source_root: Path,
        positions: bool = True,
    ) -> None:
        self._postings = postings
        self.doc_lengths = doc_lengths
        self.doc_meta = doc_meta
        self.source_root = Path(source_root)
        self.positions = positions
        self.is_closed = False
        self._cache_token = uuid4().hex

    def _ensure_open(self) -> None:
        if self.is_closed:
            raise RuntimeError("Index is closed")

    def __len__(self) -> int:
        self._ensure_open()
        return len(self._postings)

    def __iter__(self) -> Iterator[str]:
        self._ensure_open()
        return iter(self._postings)

    def __getitem__(self, term: str) -> list[Posting]:
        self._ensure_open()
        return self._postings[term]

    def __contains__(self, term: object) -> bool:
        self._ensure_open()
        return term in self._postings

    def __repr__(self) -> str:
        return f"Index(terms={len(self._postings):_}, docs={len(self.doc_meta):_})"

    @property
    def num_docs(self) -> int:
        self._ensure_open()
        return len(self.doc_meta)

    @cached_property
    def avg_doc_length(self) -> float:
        self._ensure_open()
        return sum(self.doc_lengths.values()) / self.num_docs if self.num_docs else 0.0

    def doc_length(self, doc_id: int) -> int:
        self._ensure_open()
        return self.doc_lengths[doc_id]

    def df(self, term: str) -> int:
        self._ensure_open()
        return len(self._postings.get(term, ()))

    def matched_ids(self, query: str, engine: Engine = "merge") -> set[int]:
        self._ensure_open()
        _INDEXES[self._cache_token] = self
        before = _cached_query_matches.cache_info().hits
        ids = set(_cached_query_matches(self._cache_token, query, engine))
        if _cached_query_matches.cache_info().hits > before:
            LOGGER.debug("query cache HIT for %r", query)
        return ids

    def __setstate__(self, state: dict[str, object]) -> None:
        self.__dict__.update(state)
        # Pickle round trips must never reuse another live instance's cache token.
        self._cache_token = uuid4().hex

    def close(self) -> None:
        # No open file handles after deserialization, but enforce context lifetime.
        self.is_closed = True
        _INDEXES.pop(self._cache_token, None)
        _cached_query_matches.cache_clear()


@timed
def build_index(
    root: Path,
    *,
    positions: bool = True,
    limit: int | None = None,
    progress: Callable[[int], None] | None = None,
) -> Index:
    """Single pass over lazy corpus, flushing term counts per document."""
    if limit is not None and limit < 0:
        raise ValueError("--limit must be nonnegative")
    root = Path(root).resolve()
    documents = iter_documents(root)
    if limit is not None:
        documents = islice(documents, limit)
    postings: defaultdict[str, list[Posting]] = defaultdict(list)
    lengths: dict[int, int] = {}
    metadata: dict[int, DocMeta] = {}
    for doc_id, doc in enumerate(documents):
        term_counts: Counter[str] = Counter()
        offsets: defaultdict[str, list[int]] = defaultdict(list)
        length = 0
        for i, term in enumerate(tokenize(doc.text)):
            term_counts[term] += 1
            if positions:
                offsets[term].append(i)
            length += 1
        for term, freq in term_counts.items():
            postings[term].append(
                Posting(doc_id, freq, tuple(offsets[term]) if positions else ())
            )
        lengths[doc_id] = length
        metadata[doc_id] = DocMeta(
            path=doc.path.relative_to(root).as_posix(),
            title=doc.path.stem.replace("_", " "),
        )
        if progress is not None:
            progress(doc_id + 1)
    return Index(dict(postings), lengths, metadata, root, positions)


def main() -> None:
    from findex.store import save

    parser = argparse.ArgumentParser(description="Build a persisted findex index")
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--positions", action="store_true", default=False)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    tracemalloc.start()
    start = time.perf_counter()
    try:
        ix = build_index(args.corpus, positions=args.positions, limit=args.limit)
        save(ix, args.out)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"Indexed {ix.num_docs} docs, {len(ix)} terms in {time.perf_counter()-start:.3f}s, peak {peak/1048576:.3f} MiB")


if __name__ == "__main__":
    main()
