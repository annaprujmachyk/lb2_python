"""Recursive-descent Boolean/phrase query parser.

Precedence: NOT > implicit/explicit AND > OR. Binary nodes are frozen values.
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from findex.tokenize import tokenize

if TYPE_CHECKING:
    from findex.index import Engine, Index


class QuerySyntaxError(ValueError):
    pass


class Query:
    def evaluate(self, index: "Index", engine: "Engine" = "merge") -> set[int]:
        raise NotImplementedError

    def terms(self) -> set[str]:
        raise NotImplementedError

    def __and__(self, other: "Query") -> "And":
        return And(self, other)

    def __or__(self, other: "Query") -> "Or":
        return Or(self, other)

    def __invert__(self) -> "Not":
        return Not(self)


@dataclass(frozen=True, slots=True)
class Term(Query):
    value: str

    def evaluate(self, index: "Index", engine: "Engine" = "merge") -> set[int]:
        return {posting.doc_id for posting in index._postings.get(self.value, ())}

    def terms(self) -> set[str]:
        return {self.value}


@dataclass(frozen=True, slots=True)
class Phrase(Query):
    value: tuple[str, ...]

    def evaluate(self, index: "Index", engine: "Engine" = "merge") -> set[int]:
        if not self.value:
            return set()
        if not index.positions:
            raise ValueError("Phrase queries require an index built with --positions")
        lists = [index._postings.get(term, []) for term in self.value]
        if any(not postings for postings in lists):
            return set()
        # Intersect doc IDs first. Match consecutive token positions per doc.
        common = set.intersection(*({post.doc_id for post in ps} for ps in lists))
        by_term = [{post.doc_id: post.positions for post in ps} for ps in lists]
        result: set[int] = set()
        for doc_id in common:
            starts = set(by_term[0][doc_id])
            for offset, posting_by_doc in enumerate(by_term[1:], start=1):
                starts.intersection_update({position - offset for position in posting_by_doc[doc_id]})
                if not starts:
                    break
            if starts:
                result.add(doc_id)
        return result

    def terms(self) -> set[str]:
        return set(self.value)


@dataclass(frozen=True, slots=True)
class And(Query):
    left: Query
    right: Query

    def evaluate(self, index: "Index", engine: "Engine" = "merge") -> set[int]:
        from findex.search import merge_and
        a = self.left.evaluate(index, engine)
        b = self.right.evaluate(index, engine)
        return set(merge_and(sorted(a), sorted(b))) if engine == "merge" else a & b

    def terms(self) -> set[str]:
        return self.left.terms() | self.right.terms()


@dataclass(frozen=True, slots=True)
class Or(Query):
    left: Query
    right: Query

    def evaluate(self, index: "Index", engine: "Engine" = "merge") -> set[int]:
        from findex.search import merge_or
        a = self.left.evaluate(index, engine)
        b = self.right.evaluate(index, engine)
        return set(merge_or(sorted(a), sorted(b))) if engine == "merge" else a | b

    def terms(self) -> set[str]:
        return self.left.terms() | self.right.terms()


@dataclass(frozen=True, slots=True)
class Not(Query):
    child: Query

    def evaluate(self, index: "Index", engine: "Engine" = "merge") -> set[int]:
        from findex.search import merge_not
        universe = set(index.doc_meta)
        excluded = self.child.evaluate(index, engine)
        return set(merge_not(sorted(universe), sorted(excluded))) if engine == "merge" else universe - excluded

    def terms(self) -> set[str]:
        return set()  # Negative matches should not positively affect relevance.


_PATTERN = re.compile(r'"[^"]*"|\(|\)|[^\s()"]+')


def _lex(query: str) -> list[str]:
    tokens: list[str] = []
    end = 0
    for match in _PATTERN.finditer(query):
        if query[end:match.start()].strip():
            raise QuerySyntaxError("Invalid token or unmatched quote")
        tokens.append(match.group())
        end = match.end()
    if query[end:].strip():
        raise QuerySyntaxError("Invalid token or unmatched quote")
    return tokens


class _Parser:
    def __init__(self, tokens: list[str]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def pop(self) -> str:
        token = self.peek()
        if token is None:
            raise QuerySyntaxError("Unexpected end of query")
        self.pos += 1
        return token

    def accept(self, value: str) -> bool:
        if self.peek() is not None and self.peek().upper() == value:
            self.pop()
            return True
        return False

    def parse_or(self) -> Query:
        node = self.parse_and()
        while self.accept("OR"):
            node = Or(node, self.parse_and())
        return node

    def parse_and(self) -> Query:
        node = self.parse_not()
        while True:
            if self.accept("AND"):
                node = And(node, self.parse_not())
            elif self.peek() is not None and self.peek() != ")" and self.peek().upper() != "OR":
                node = And(node, self.parse_not())  # implicit AND
            else:
                return node

    def parse_not(self) -> Query:
        return Not(self.parse_not()) if self.accept("NOT") else self.parse_atom()

    def parse_atom(self) -> Query:
        token = self.pop()
        if token == "(":
            node = self.parse_or()
            if self.pop() != ")":
                raise QuerySyntaxError("Missing closing parenthesis")
            return node
        if token == ")" or token.upper() in {"AND", "OR"}:
            raise QuerySyntaxError(f"Unexpected token {token!r}")
        if token.startswith('"'):
            words = tuple(tokenize(token[1:-1]))
            if not words:
                raise QuerySyntaxError("Empty quoted phrase")
            return Phrase(words)
        words = list(tokenize(token))
        if len(words) != 1:
            raise QuerySyntaxError(f"Expected one term, found {token!r}")
        return Term(words[0])


def parse(query: str) -> Query:
    tokens = _lex(query)
    if not tokens:
        raise QuerySyntaxError("Query must not be empty")
    parser = _Parser(tokens)
    expression = parser.parse_or()
    if parser.peek() is not None:
        raise QuerySyntaxError(f"Unexpected trailing token {parser.peek()!r}")
    return expression
