"""Persist an index as JSON (safe) or pickle (only for locally trusted files)."""

import json
import pickle
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

from findex.index import Index
from findex.models import DocMeta, Posting
from findex.timing import timed

FORMAT_VERSION = 1


def _to_json(index: Index) -> dict[str, object]:
    return {
        "version": FORMAT_VERSION,
        "source_root": str(index.source_root),
        "positions": index.positions,
        "postings": {term: [[p.doc_id, p.tf, list(p.positions)] for p in ps] for term, ps in index.items()},
        "doc_lengths": {str(key): value for key, value in index.doc_lengths.items()},
        "doc_meta": {str(key): {"path": m.path, "title": m.title} for key, m in index.doc_meta.items()},
    }


def _from_json(raw: dict[str, Any]) -> Index:
    if raw.get("version") != FORMAT_VERSION:
        raise ValueError("Unsupported index format version")
    # Validate payload before constructing domain objects; JSON is data, not code.
    posting_data = cast(dict[str, list[list[object]]], raw["postings"])
    lengths_data = cast(dict[str, int], raw["doc_lengths"])
    metadata_data = cast(dict[str, dict[str, str]], raw["doc_meta"])
    postings = {
        term: [Posting(int(p[0]), int(p[1]), tuple(int(pos) for pos in cast(list[int], p[2]))) for p in rows]
        for term, rows in posting_data.items()
    }
    return Index(
        postings,
        {int(doc_id): int(n) for doc_id, n in lengths_data.items()},
        {int(doc_id): DocMeta(str(meta["path"]), str(meta["title"])) for doc_id, meta in metadata_data.items()},
        Path(str(raw["source_root"])),
        bool(raw["positions"]),
    )


@timed
def save(index: Index, path: Path) -> None:
    """'.json' selects JSON; '.bin'/'.pkl' selects pickle."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        path.write_text(json.dumps(_to_json(index), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    elif path.suffix in (".bin", ".pkl", ".pickle"):
        with path.open("wb") as stream:
            pickle.dump(index, stream, protocol=pickle.HIGHEST_PROTOCOL)
    else:
        raise ValueError("Index filename must end in .json, .bin or .pkl")


@timed
def load(path: Path) -> Index:
    path = Path(path)
    if path.suffix == ".json":
        content: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(content, dict):
            raise ValueError("Index JSON must contain an object")
        return _from_json(cast(dict[str, Any], content))
    if path.suffix in (".bin", ".pkl", ".pickle"):
        # SECURITY: pickle can execute arbitrary code during deserialization.
        # NEVER load a pickle downloaded from someone else or an untrusted source.
        with path.open("rb") as stream:
            result: object = pickle.load(stream)  # noqa: S301
        if not isinstance(result, Index):
            raise ValueError("Pickle did not contain an Index")
        return result
    raise ValueError("Index filename must end in .json, .bin or .pkl")


@contextmanager
def open_index(path: Path) -> Iterator[Index]:
    index = load(path)
    try:
        yield index
    finally:
        index.close()
