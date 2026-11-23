"""Lazy ingestion of UTF-8 text documents from a directory tree."""

import logging
from pathlib import Path
from typing import Iterator, NamedTuple

LOGGER = logging.getLogger(__name__)


class Document(NamedTuple):
    doc_id: str
    path: Path
    text: str


def iter_documents(root: Path) -> Iterator[Document]:
    """Yield one document at a time in filesystem traversal order.

    Invalid UTF-8 bytes are replaced and logged rather than aborting the run.
    At most one complete document's text is held by this generator.
    """
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(f"Corpus directory not found: {root}")

    # Path.rglob returns a lazy iterator. Sorting would materialize paths;
    # filesystem iteration order is intentionally retained to stay lazy.
    for path in root.rglob("*.txt"):
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="strict") as stream:
                text = stream.read()
        except UnicodeDecodeError:
            LOGGER.warning("Invalid UTF-8 in %s; replacing invalid bytes", path)
            try:
                with path.open("r", encoding="utf-8", errors="replace") as stream:
                    text = stream.read()
            except OSError as exc:
                LOGGER.warning("Skipping unreadable file %s: %s", path, exc)
                continue
        except OSError as exc:
            LOGGER.warning("Skipping unreadable file %s: %s", path, exc)
            continue
        yield Document(doc_id=path.relative_to(root).as_posix(), path=path, text=text)
