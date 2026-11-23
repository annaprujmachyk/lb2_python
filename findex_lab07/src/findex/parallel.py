"""Spawn-safe map/reduce indexing using local documents and compact partial postings.

Workers receive *paths*, not document bodies. No mutable index is shared.
"""
from __future__ import annotations

import logging
import multiprocessing
import os
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Callable, Iterable, Literal

from findex.index import Index
from findex.models import DocMeta, Posting
from findex.tokenize import tokenize

LOGGER = logging.getLogger(__name__)
ExecutorKind = Literal['serial', 'threads', 'processes']

@dataclass(slots=True)
class PartialIndex:
    postings: dict[str, list[Posting]]
    doc_lengths: dict[int, int]
    doc_meta: dict[int, DocMeta]

@dataclass(frozen=True, slots=True)
class BuildMetrics:
    build_seconds: float
    merge_seconds: float
    total_seconds: float


def _read_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        LOGGER.warning('Invalid UTF-8 in %s; replacing invalid bytes', path)
        try:
            return path.read_text(encoding='utf-8', errors='replace')
        except OSError as exc:
            LOGGER.warning('Skipping unreadable file %s: %s', path, exc)
            return None
    except OSError as exc:
        LOGGER.warning('Skipping unreadable file %s: %s', path, exc)
        return None


def build_partial(
    doc_paths: list[Path], *, root: Path | None = None,
    start_id: int = 0, positions: bool = True,
) -> PartialIndex:
    """Build a partial index with globally assigned doc IDs.

    Caller assigns consecutive [start_id, start_id + len(doc_paths)) ranges;
    unreadable files are skipped (their ID becomes a gap).
    """
    if root is None:
        root = Path(os.path.commonpath([str(p.parent) for p in doc_paths])) if doc_paths else Path('.')
    postings: defaultdict[str, list[Posting]] = defaultdict(list)
    lengths: dict[int, int] = {}
    metadata: dict[int, DocMeta] = {}
    for offset, path in enumerate(doc_paths):
        content = _read_file(path)
        if content is None:
            continue
        doc_id = start_id + offset
        terms: Counter[str] = Counter()
        offsets: defaultdict[str, list[int]] = defaultdict(list)
        size = 0
        for i, word in enumerate(tokenize(content)):
            terms[word] += 1
            if positions:
                offsets[word].append(i)
            size += 1
        for word, count in terms.items():
            postings[word].append(Posting(doc_id, count, tuple(offsets[word]) if positions else ()))
        lengths[doc_id] = size
        metadata[doc_id] = DocMeta(
            path=path.relative_to(root).as_posix(),
            title=path.stem.replace('_', ' '),
        )
    return PartialIndex(dict(postings), lengths, metadata)


def _worker(task: tuple[list[Path], Path, int, bool]) -> PartialIndex:
    paths, root, start_id, positions = task
    return build_partial(paths, root=root, start_id=start_id, positions=positions)


def merge(
    partials: Iterable[PartialIndex], *, source_root: Path = Path('.'),
    positions: bool = True,
) -> Index:
    """Merge disjoint document ranges; posting lists sorted by global ID."""
    postings: defaultdict[str, list[Posting]] = defaultdict(list)
    lengths: dict[int, int] = {}
    metadata: dict[int, DocMeta] = {}
    for part in partials:
        if lengths.keys() & part.doc_lengths.keys():
            raise ValueError('Overlapping document IDs between partial indexes')
        lengths.update(part.doc_lengths)
        metadata.update(part.doc_meta)
        for term, ps in part.postings.items():
            postings[term].extend(ps)
    # Sorted term insertion order matches the single-threaded index only when
    # source-order chunks are merged, but postings always have sorted doc IDs.
    for ps in postings.values():
        ps.sort(key=lambda posting: posting.doc_id)
    return Index(dict(postings), lengths, metadata, Path(source_root), positions)


def _make_chunks(
    paths: list[Path], root: Path, workers: int, positions: bool,
    chunk_size: int | None = None,
) -> list[tuple[list[Path], Path, int, bool]]:
    if chunk_size is not None and chunk_size < 1:
        raise ValueError('chunk_size must be >= 1')
    # Limit tiny tasks to avoid enormous pickling/queue overhead.
    size = chunk_size or max(1, (len(paths) + workers * 4 - 1) // (workers * 4))
    return [(paths[i:i+size], root, i, positions) for i in range(0, len(paths), size)]


def build_parallel_index(
    root: Path, *, executor: ExecutorKind = 'serial', workers: int = 1,
    positions: bool = True, limit: int | None = None,
    chunk_size: int | None = None,
    progress: Callable[[int], None] | None = None,
) -> tuple[Index, BuildMetrics]:
    """Produce the same index under all three execution strategies.

    Keep process invocation at an actual CLI entry point guarded by __main__.
    """
    if workers < 1:
        raise ValueError('--workers must be >= 1')
    if limit is not None and limit < 0:
        raise ValueError('--limit must be nonnegative')
    if executor not in ('serial', 'threads', 'processes'):
        raise ValueError(f'Unknown executor: {executor}')
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f'Corpus directory not found: {root}')
    start = time.perf_counter()
    # Path listing, unlike content loading, is cheap. The user file traversal
    # order matches iter_documents() from Lab 01/04.
    candidates = (p for p in root.rglob('*.txt') if p.is_file())
    paths = list(islice(candidates, limit)) if limit is not None else list(candidates)
    tasks = _make_chunks(paths, root, workers, positions, chunk_size)
    # For serial, one chunk exactly reproduces the baseline stream.
    if executor == 'serial':
        tasks = [(paths, root, 0, positions)] if paths else []
    chunks: list[PartialIndex] = []
    if executor == 'serial':
        for task in tasks:
            chunks.append(_worker(task))
            if progress is not None:
                progress(len(chunks[-1].doc_lengths))
    else:
        pool_type = ThreadPoolExecutor if executor == 'threads' else ProcessPoolExecutor
        with pool_type(max_workers=workers, **({'mp_context': multiprocessing.get_context('spawn')} if executor == 'processes' else {})) as pool:
            # map preserves task order and propagates original worker failures.
            for part in pool.map(_worker, tasks):
                chunks.append(part)
                if progress is not None:
                    progress(len(part.doc_lengths))
    before_merge = time.perf_counter()
    result = merge(chunks, source_root=root, positions=positions)
    end = time.perf_counter()
    return result, BuildMetrics(before_merge - start, end - before_merge, end - start)
