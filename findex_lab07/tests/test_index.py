from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from findex.index import Index, build_index
from findex.models import DocMeta, Posting


def test_build_five_docs(index: Index):
    assert index.num_docs == 5


def test_term_present(index: Index):
    assert "python" in index
    assert "notfound" not in index


def test_getitem_and_df(index: Index):
    assert index.df("python") == 2
    assert len(index["python"]) == 2


def test_missing_term_keyerror(index: Index):
    with pytest.raises(KeyError):
        _ = index["nonexistent"]


def test_len_and_iter(index: Index):
    assert len(list(index)) == len(index)
    assert "python" in list(index)


def test_repr(index: Index):
    assert repr(index).startswith("Index(terms=")
    assert "docs=5" in repr(index)


def test_doc_lengths_and_average(index: Index):
    assert sum(index.doc_lengths.values()) > 0
    assert index.avg_doc_length == sum(index.doc_lengths.values()) / 5


def test_sorted_postings(index: Index):
    for postings in index.values():
        assert [p.doc_id for p in postings] == sorted(p.doc_id for p in postings)


def test_tf_and_positions(index: Index):
    assert sorted(p.tf for p in index["python"]) == [2, 3]
    for posting in index["python"]:
        assert len(posting.positions) == posting.tf


def test_hashable_records():
    assert len({Posting(1, 2), Posting(1, 2)}) == 1
    assert len({DocMeta("a", "A"), DocMeta("a", "A")}) == 1


def test_frozen_records():
    posting = Posting(1, 2)
    with pytest.raises(FrozenInstanceError):
        posting.tf = 3  # type: ignore[misc]


def test_without_positions(corpus: Path):
    index = build_index(corpus, positions=False)
    assert all(not p.positions for posts in index.values() for p in posts)


def test_limit_zero(corpus: Path):
    assert build_index(corpus, limit=0).num_docs == 0


def test_negative_limit(corpus: Path):
    with pytest.raises(ValueError):
        build_index(corpus, limit=-1)


def test_closed_index(index: Index):
    index.close()
    with pytest.raises(RuntimeError):
        len(index)
