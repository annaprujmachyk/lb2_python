"""Create a compact, deterministic corpus designed for ranking and query demos."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data" / "demo"
DOCUMENTS = {
    "01_python_basics.txt": "Python is an accessible programming language. Python uses functions and generators. Learn to write a program.",
    "02_async_python.txt": "Python supports async await syntax. Async Python applications use an event loop for concurrency. Async tasks are cooperative.",
    "03_javascript_async.txt": "JavaScript offers async await and an event loop. JavaScript promises organize browser work.",
    "04_inverted_index.txt": "An inverted index maps terms to documents. Search engines index documents to support fast search queries.",
    "05_bm25_ranking.txt": "BM25 is a ranking algorithm for search engines. BM25 combines term frequency, inverse document frequency, and document length normalization.",
    "06_tfidf_ranking.txt": "TF IDF computes word importance for document ranking. TF IDF is useful for a simple search engine.",
    "07_generator_streaming.txt": "Python generators yield values lazily. A generator streams records without creating a large list. Streaming reduces memory.",
    "08_unicode_words.txt": "Unicode search must normalize Straße and STRASSE. Café and café should match after normalization.",
    "09_dataclasses.txt": "Python dataclasses store lightweight records. Frozen dataclasses are hashable, and slots reduce memory use.",
    "10_testing.txt": "Tests verify Python code. Pytest supports fixtures and parametrization. Hypothesis generates random test inputs.",
    "11_packaging.txt": "Packaging a Python project with uv produces a wheel. Typer and Rich make a friendly command line interface.",
    "12_backend.txt": "Backend development uses databases, servers, HTTP and application programming interfaces. API design helps clients.",
    "13_search_python.txt": "Python search engine builds an inverted index. Python search query uses ranking.",
    "14_frontend.txt": "Frontend frameworks like Angular help build JavaScript interfaces. Angular uses TypeScript and components.",
    "15_phrase.txt": "The quick brown fox jumps. A quick blue bird flies. Exact phrase matching requires word positions.",
}


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, content in DOCUMENTS.items():
        (ROOT / name).write_text(content, encoding="utf-8")
    print(f"Created {len(DOCUMENTS)} UTF-8 documents in {ROOT}")


if __name__ == "__main__":
    main()
