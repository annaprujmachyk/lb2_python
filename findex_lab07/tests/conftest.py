"""Shared small corpus/index; tests remain isolated via fresh tmp_path directories."""

from pathlib import Path

import pytest

from findex.index import Index, build_index


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    texts = {
        "a.txt": "Python async await. Python is fun. Quick brown fox.",
        "b.txt": "JavaScript async await. Quick blue bird.",
        "c.txt": "Python generators stream text. Python. Python.",
        "d.txt": "Unicode Straße CAFÉ cafe\u0301.",
        "empty.txt": "",
    }
    for name, text in texts.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


@pytest.fixture
def index(corpus: Path) -> Index:
    return build_index(corpus)
