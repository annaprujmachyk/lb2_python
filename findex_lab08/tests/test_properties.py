"""Three Hypothesis properties; installed via uv sync --dev in CI.

The creation environment cannot download Hypothesis: these tests skip locally
if unavailable, but run in CI once the dependency is installed.
"""

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, strategies as st

from findex.search import merge_and, merge_or
from findex.tokenize import tokenize


@given(st.lists(st.integers(min_value=0, max_value=100), unique=True), st.lists(st.integers(min_value=0, max_value=100), unique=True))
def test_property_merge_and_matches_set(a, b):
    assert merge_and(sorted(a), sorted(b)) == sorted(set(a) & set(b))


@given(st.lists(st.integers(min_value=0, max_value=100), unique=True), st.lists(st.integers(min_value=0, max_value=100), unique=True))
def test_property_merge_or_matches_set(a, b):
    assert merge_or(sorted(a), sorted(b)) == sorted(set(a) | set(b))


@given(st.text())
def test_property_tokenizer_is_idempotent(text):
    tokens = list(tokenize(text))
    assert list(tokenize(" ".join(tokens))) == tokens
