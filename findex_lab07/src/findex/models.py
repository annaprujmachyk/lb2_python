"""Hashable, memory-efficient records for the index and search results."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Posting:
    doc_id: int
    tf: int
    positions: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class DocMeta:
    path: str  # relative to index.source_root
    title: str


@dataclass(frozen=True, slots=True, order=True)
class SearchResult:
    """Sorts highest score first; tie-breaks by document ID."""

    sort_key: float = field(init=False, repr=False)
    doc_id: int
    score: float = field(compare=False)
    title: str = field(compare=False)
    snippet: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sort_key", -self.score)

    def __str__(self) -> str:
        return f"{self.score:7.3f}  {self.title}: {self.snippet}"
