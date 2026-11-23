import logging
from pathlib import Path

import pytest

from findex.index import Index, build_index
from findex.ranking import BM25, TfIdf, search
from findex.store import load, open_index, save


@pytest.mark.parametrize("ext", ["json", "bin"])
def test_round_trip(index: Index, tmp_path: Path, ext: str):
    target = tmp_path / f"index.{ext}"
    save(index, target)
    loaded = load(target)
    assert loaded == index
    assert loaded.positions == index.positions


def test_context_manager_closes(index: Index, tmp_path: Path):
    target = tmp_path / "index.json"
    save(index, target)
    with open_index(target) as loaded:
        assert loaded.num_docs == 5
    assert loaded.is_closed
    with pytest.raises(RuntimeError):
        loaded.df("python")


def test_context_manager_closes_on_error(index: Index, tmp_path: Path):
    target = tmp_path / "index.json"
    save(index, target)
    with pytest.raises(ValueError):
        with open_index(target) as loaded:
            raise ValueError("test")
    assert loaded.is_closed


def test_unrecognized_extension(index: Index, tmp_path: Path):
    with pytest.raises(ValueError):
        save(index, tmp_path / "index.zzz")


def test_tfidf_finite(index: Index):
    assert TfIdf().score("python", index["python"][0], index) > 0


def test_bm25_finite(index: Index):
    assert BM25().score("python", index["python"][0], index) > 0


def test_bm25_params():
    for kwargs in ({"k1": 0}, {"b": -0.1}, {"b": 1.1}):
        with pytest.raises(ValueError):
            BM25(**kwargs)


def test_results_ranked(index: Index):
    results = search(index, "python", scorer=BM25())
    assert results == sorted(results)
    assert results[0].score >= results[-1].score


def test_search_limit(index: Index):
    assert len(search(index, "python OR javascript", k=1)) == 1
    assert len(search(index, "python", k=0)) == 0
    with pytest.raises(ValueError):
        search(index, "python", k=-1)


def test_snippets_highlight(index: Index):
    results = search(index, "python")
    assert "[[Python]]" in " ".join(row.snippet for row in results)


def test_cache_hit(index: Index, caplog):
    with caplog.at_level(logging.DEBUG):
        search(index, "python")
        search(index, "python")
    assert "cache HIT" in caplog.text


def test_rare_term_ranks_higher(tmp_path: Path):
    (tmp_path / "common.txt").write_text("common common", encoding="utf-8")
    (tmp_path / "rare.txt").write_text("common rare", encoding="utf-8")
    (tmp_path / "other.txt").write_text("common unrelated", encoding="utf-8")
    ix = build_index(tmp_path)
    p = ix["common"][0]
    rare = ix["rare"][0]
    assert BM25().score("rare", rare, ix) > BM25().score("common", p, ix)


def test_tf_saturation(tmp_path: Path):
    for name, n in (("a.txt", 1), ("b.txt", 19), ("c.txt", 20), ("d.txt", 1)):
        (tmp_path / name).write_text(("apple " * n if name != "d.txt" else "other"), encoding="utf-8")
    ix = build_index(tmp_path)
    by_tf = {p.tf: p for p in ix["apple"]}
    bm = BM25(b=0)
    assert bm.score("apple", by_tf[20], ix) - bm.score("apple", by_tf[19], ix) < 0.02


def test_short_doc_advantage(tmp_path: Path):
    (tmp_path / "short.txt").write_text("rare", encoding="utf-8")
    (tmp_path / "long.txt").write_text("rare " + "other " * 100, encoding="utf-8")
    (tmp_path / "none.txt").write_text("other", encoding="utf-8")
    ix = build_index(tmp_path)
    ranked = search(ix, "rare")
    assert ranked[0].title == "short"


def test_empty_corpus(tmp_path: Path):
    ix = build_index(tmp_path)
    assert search(ix, "anything") == []
