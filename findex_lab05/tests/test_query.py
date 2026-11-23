import pytest

from findex.index import Index, build_index
from findex.query import And, Not, Or, Phrase, QuerySyntaxError, Term, parse


def test_parse_precedence():
    assert parse("a OR b c") == Or(Term("a"), And(Term("b"), Term("c")))


def test_parse_explicit_and():
    assert parse("a AND b") == And(Term("a"), Term("b"))


def test_parse_parentheses():
    assert parse("a AND (b OR c)") == And(Term("a"), Or(Term("b"), Term("c")))


def test_parse_not():
    assert parse("python NOT java") == And(Term("python"), Not(Term("java")))


def test_parse_phrase():
    assert parse('"Async Await"') == Phrase(("async", "await"))


def test_query_operators():
    assert Term("a") & (Term("b") | ~Term("c")) == And(Term("a"), Or(Term("b"), Not(Term("c"))))


def test_casefold_query():
    assert parse("STRASSE") == Term("strasse")


@pytest.mark.parametrize("text", ["", " ", "(python", "python)", "python OR", "AND python", '"unterminated', '""'])
def test_invalid_syntax(text):
    with pytest.raises(QuerySyntaxError):
        parse(text)


def test_phrase_matches_only_adjacent(index: Index):
    assert len(parse('"quick brown"').evaluate(index)) == 1
    assert len(parse('"quick fox"').evaluate(index)) == 0


def test_phrase_requires_positions(corpus):
    ix = build_index(corpus, positions=False)
    with pytest.raises(ValueError, match="positions"):
        parse('"quick brown"').evaluate(ix)


def test_nested_not(index: Index):
    assert parse("NOT NOT python").evaluate(index) == parse("python").evaluate(index)
