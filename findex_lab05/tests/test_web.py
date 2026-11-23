"""Перевірка API, HTML та впровадження тестових залежностей."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from findex.index import build_index
from findex.web.app import Settings, create_app, get_index, get_settings, highlighted_html


@pytest.fixture
def client(tmp_path: Path):
    (tmp_path / "alpha.txt").write_text("python python код пошук", encoding="utf-8")
    (tmp_path / "beta.txt").write_text("python async код", encoding="utf-8")
    (tmp_path / "gamma.txt").write_text("інший текст", encoding="utf-8")
    index = build_index(tmp_path)
    app = create_app(Settings(index_path=tmp_path / "missing.json"))
    app.dependency_overrides[get_index] = lambda: index
    app.dependency_overrides[get_settings] = lambda: Settings(index_path=tmp_path / "other.json")
    cli = TestClient(app)
    yield cli
    index.close()


def test_search_response(client):
    response = client.get("/search", params={"q": "python"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["results"]) == 2
    assert {"query", "total", "results", "took_ms"} <= data.keys()
    assert response.headers.get("X-Request-ID")


@pytest.mark.parametrize("params", [
    {}, {"q": ""}, {"q": "x"*201}, {"q": "python", "k": 0},
    {"q": "python", "k": 101}, {"q": "python", "k": "abc"},
    {"q": "python", "scorer": "bad"}, {"q": "python", "page": 0},
])
def test_validation_422(client, params):
    response = client.get("/search", params=params)
    assert response.status_code == 422
    assert "detail" in response.json()


def test_pagination(client):
    first = client.get("/search", params={"q": "python", "k": 1, "page": 1}).json()
    second = client.get("/search", params={"q": "python", "k": 1, "page": 2}).json()
    third = client.get("/search", params={"q": "python", "k": 1, "page": 3}).json()
    assert first["total"] == second["total"] == 2
    assert first["results"][0]["doc_id"] != second["results"][0]["doc_id"]
    assert third["results"] == []


def test_tfidf(client):
    assert client.get("/search", params={"q": "python", "scorer": "tfidf"}).status_code == 200


def test_docs_and_404(client):
    result = client.get("/docs/0")
    assert result.status_code == 200
    assert "python" in result.json()["text"]
    assert client.get("/docs/9999").status_code == 404
    assert client.get("/doc/9999").status_code == 404
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_stats(client):
    result = client.get("/stats")
    assert result.status_code == 200
    assert result.json()["documents"] == 3
    assert result.json()["vocabulary"] > 0


def test_ui(client):
    response = client.get("/", params={"q":"python", "k":1})
    assert response.status_code == 200
    assert 'lang="uk"' in response.text
    assert "Наступна" in response.text
    assert client.get("/doc/0").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_html_escaped():
    assert "<script>" not in highlighted_html("[[<script>]]")
    assert "&lt;script&gt;" in highlighted_html("[[<script>]]")


def test_health_503_if_unloaded(tmp_path):
    app = create_app(Settings(index_path=tmp_path / "missing.json"))
    # Без lifespan стартовий індекс відсутній: /health повертає 503.
    cli = TestClient(app)
    assert cli.get("/health").status_code == 503
    assert cli.get("/stats").status_code == 503


def test_lifespan_load_and_shutdown(tmp_path):
    from findex.store import save
    folder = tmp_path / "source"
    folder.mkdir()
    (folder / "a.txt").write_text("привіт python", encoding="utf-8")
    ix = build_index(folder)
    save(ix, tmp_path / "index.json")
    app = create_app(Settings(index_path=tmp_path / "index.json"))
    with TestClient(app) as cli:
        assert cli.get("/health").json() == {"status": "ok"}
        assert cli.get("/search", params={"q":"python"}).json()["total"] == 1
        loaded = app.state.index
    assert loaded.is_closed
    assert app.state.index is None


def test_missing_index_rejected_on_startup(tmp_path):
    app = create_app(Settings(index_path=tmp_path / "missing.json"))
    with pytest.raises(FileNotFoundError):
        with TestClient(app):
            pass


def test_settings_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_PATH", str(tmp_path / "my.json"))
    monkeypatch.setenv("PORT", "9234")
    config = Settings()
    assert config.index_path == tmp_path / "my.json"
    assert config.port == 9234
