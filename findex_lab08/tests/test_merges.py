import pytest

from findex.index import Index
from findex.search import boolean_search, merge_and, merge_not, merge_or


@pytest.mark.parametrize("a,b,want", [
    ([], [], []),
    ([1, 3, 5], [2, 4], []),
    ([1, 2, 7], [2, 7, 10], [2, 7]),
    ([1], [1], [1]),
])
def test_merge_and(a, b, want):
    assert merge_and(a, b) == want


@pytest.mark.parametrize("a,b,want", [
    ([], [], []),
    ([1, 3], [2, 3], [1, 2, 3]),
    ([5, 7], [], [5, 7]),
    ([], [1, 2], [1, 2]),
])
def test_merge_or(a, b, want):
    assert merge_or(a, b) == want


def test_merge_not():
    assert merge_not([1, 2, 3, 4], [2, 4, 8]) == [1, 3]


def test_boolean_and(index: Index):
    assert len(boolean_search(index, "python async")) == 1


def test_boolean_or(index: Index):
    assert len(boolean_search(index, "python OR javascript")) == 3


def test_boolean_not(index: Index):
    assert len(boolean_search(index, "python NOT async")) == 1


def test_engines_agree(index: Index):
    for query in ("python", "python OR javascript", "async NOT python", '"quick brown" OR café'):
        assert boolean_search(index, query, "merge") == boolean_search(index, query, "set")
