from inspect import isgeneratorfunction

from findex.tokenize import tokenize


def test_casefold():
    assert list(tokenize("Hello HELLO")) == ["hello", "hello"]


def test_cyrillic():
    assert list(tokenize("Привіт Україна")) == ["привіт", "україна"]


def test_combining_accent():
    assert list(tokenize("café cafe\u0301")) == ["café", "café"]


def test_punctuation():
    assert list(tokenize("Hello, world!")) == ["hello", "world"]


def test_empty():
    assert list(tokenize("")) == []


def test_apostrophe():
    assert list(tokenize("don't п'ять")) == ["don", "t", "п", "ять"]


def test_hyphen():
    assert list(tokenize("state-of-the-art")) == ["state", "of", "the", "art"]


def test_digits():
    assert list(tokenize("Python3 2026")) == ["python3", "2026"]


def test_german_sharp_s():
    assert list(tokenize("Straße STRASSE")) == ["strasse", "strasse"]


def test_is_generator():
    assert isgeneratorfunction(tokenize)
