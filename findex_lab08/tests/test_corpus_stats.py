from inspect import isgeneratorfunction

import pytest

from findex.corpus import iter_documents
from findex.stats import eager_stats, lazy_stats


def test_document_generator_and_lazy_first_yield(tmp_path):
    (tmp_path / "one.txt").write_text("Hello World", encoding="utf-8")
    assert isgeneratorfunction(iter_documents)
    first = next(iter_documents(tmp_path))
    assert first.doc_id == "one.txt"
    assert first.text == "Hello World"


def test_bad_utf8_replaced(tmp_path, caplog):
    (tmp_path / "invalid.txt").write_bytes(b"Hi \xff world")
    documents = list(iter_documents(tmp_path))
    assert len(documents) == 1
    assert "\ufffd" in documents[0].text
    assert "Invalid UTF-8" in caplog.text


def test_stats_and_limit(tmp_path):
    (tmp_path / "a.txt").write_text("Hi hi", encoding="utf-8")
    (tmp_path / "b.txt").write_text("World!", encoding="utf-8")
    full = lazy_stats(tmp_path)
    assert full.documents == 2
    assert full.tokens == 3
    assert full.vocabulary == 2
    assert eager_stats(tmp_path).frequencies == full.frequencies
    assert lazy_stats(tmp_path, 0).documents == 0
    assert lazy_stats(tmp_path, 1).documents == 1


def test_missing_root(tmp_path):
    with pytest.raises(NotADirectoryError):
        next(iter_documents(tmp_path / "missing"))
