"""Composable TF-IDF and BM25 ranking using a structural Scorer protocol."""

import heapq
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Protocol

from findex.index import Index
from findex.models import Posting, SearchResult
from findex.query import parse
from findex.timing import timed


class Scorer(Protocol):
    def score(self, term: str, posting: Posting, index: Index) -> float: ...


class TfIdf:
    def score(self, term: str, posting: Posting, index: Index) -> float:
        idf = math.log((index.num_docs + 1) / (index.df(term) + 1)) + 1
        return (1 + math.log(posting.tf)) * idf


class BM25:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        if k1 <= 0 or not 0 <= b <= 1:
            raise ValueError("BM25 needs k1 > 0 and 0 <= b <= 1")
        self.k1, self.b = k1, b

    def score(self, term: str, posting: Posting, index: Index) -> float:
        n, df = index.num_docs, index.df(term)
        idf = math.log1p((n - df + 0.5) / (df + 0.5))
        avg = index.avg_doc_length or 1.0
        norm = 1 - self.b + self.b * index.doc_length(posting.doc_id) / avg
        return idf * posting.tf * (self.k1 + 1) / (posting.tf + self.k1 * norm)


def make_snippet(index: Index, doc_id: int, terms: set[str], radius: int = 80) -> str:
    """Read only the matching document; highlight matches with [[square brackets]]."""
    path = Path(index.source_root) / index.doc_meta[doc_id].path
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(source text unavailable)"
    if not text:
        return ""
    if not terms:
        return text[: 2 * radius].replace("\n", " ")
    pattern = re.compile("|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)), flags=re.IGNORECASE)
    match = pattern.search(text)
    start = max(0, match.start() - radius) if match else 0
    end = min(len(text), (match.end() + radius if match else 2 * radius))
    segment = text[start:end].replace("\n", " ")
    segment = pattern.sub(lambda m: "[[" + m.group() + "]]", segment)
    return ("…" if start else "") + segment + ("…" if end < len(text) else "")


@timed
def search(index: Index, query: str, *, scorer: Scorer | None = None, k: int = 10) -> list[SearchResult]:
    if k < 0:
        raise ValueError("k must be nonnegative")
    ranker = scorer if scorer is not None else BM25()
    tree = parse(query)
    matched = index.matched_ids(query)
    terms = tree.terms()
    scores: defaultdict[int, float] = defaultdict(float)
    # A pure negative query gets zero-scored results, not an empty list.
    for doc_id in matched:
        scores[doc_id] = 0.0
    for term in terms:
        for posting in index._postings.get(term, ()):
            if posting.doc_id in matched:
                scores[posting.doc_id] += ranker.score(term, posting, index)
    top = heapq.nlargest(k, scores.items(), key=lambda pair: (pair[1], -pair[0]))
    return [
        SearchResult(doc_id=doc_id, score=score, title=index.doc_meta[doc_id].title,
                     snippet=make_snippet(index, doc_id, terms))
        for doc_id, score in top
    ]
