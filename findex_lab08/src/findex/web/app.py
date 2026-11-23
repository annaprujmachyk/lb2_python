"""FastAPI застосунок: REST API, HTML-сторінки та керування життєвим циклом."""
from __future__ import annotations

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from findex.index import Index
from findex.ranking import BM25, TfIdf, search as rank_search
from findex.store import load

logger = logging.getLogger("findex.web")
WEB_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Налаштування, які можна перевизначати змінними середовища."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    index_path: Path = Path("data/demo.json")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    port: int = Field(default=8000, ge=1, le=65535)


class SearchResult(BaseModel):
    doc_id: int
    title: str
    score: float
    snippet: str


class SearchResponse(BaseModel):
    query: str
    total: int
    took_ms: float
    results: list[SearchResult]


class StatsResponse(BaseModel):
    documents: int
    vocabulary: int
    tokens: int
    uptime_seconds: float


class DocumentResponse(BaseModel):
    doc_id: int
    title: str
    text: str


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_index(request: Request) -> Index:
    index: Index | None = getattr(request.app.state, "index", None)
    if index is None or index.is_closed:
        raise HTTPException(status_code=503, detail="Пошуковий індекс недоступний")
    return index


def get_document(index: Index, doc_id: int) -> DocumentResponse:
    if doc_id not in index.doc_meta:
        raise HTTPException(status_code=404, detail="Документ не знайдено")
    meta = index.doc_meta[doc_id]
    # Джерела crawler можуть бути URL, а не локальними файлами.
    if meta.path.startswith(("https://", "http://")):
        return DocumentResponse(doc_id=doc_id, title=meta.title, text="Текст вебсторінки не збережений в індексі. Джерело: " + meta.path)
    root = index.source_root.resolve()
    filepath = (root / meta.path).resolve()
    if not filepath.is_relative_to(root):
        raise HTTPException(status_code=404, detail="Документ недоступний")
    try:
        content = filepath.read_text(encoding="utf-8")
    except OSError:
        raise HTTPException(status_code=404, detail="Файл документа недоступний") from None
    return DocumentResponse(doc_id=doc_id, title=meta.title, text=content)


def highlighted_html(snippet: str) -> str:
    """Безпечна підсвітка збігів [[слово]]: HTML спочатку екранується."""
    return "".join(
        f"<mark>{escape(part[2:-2])}</mark>" if part.startswith("[[") and part.endswith("]]") else escape(part)
        for part in re.split(r"(\[\[.*?\]\])", snippet)
    )


def query_results(index: Index, q: str, k: int, scorer: str, page: int) -> SearchResponse:
    started = time.perf_counter()
    try:
        # Повертаємо лише одну сторінку, а загальне число збігів обчислюємо окремо.
        matched = index.matched_ids(q)
        found = rank_search(index, q, k=min(k * page, index.num_docs), scorer=BM25() if scorer == "bm25" else TfIdf())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Некоректний запит: {exc}") from exc
    page_results = found[(page - 1) * k : page * k]
    return SearchResponse(query=q, total=len(matched), took_ms=round((time.perf_counter()-started)*1000, 3),
                          results=[SearchResult(doc_id=r.doc_id, title=r.title, score=r.score, snippet=r.snippet) for r in page_results])


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        logging.getLogger("findex.web").setLevel(config.log_level)
        application.state.index = load(config.index_path)
        application.state.started_at = time.monotonic()
        logger.info("Індекс завантажено: %s", config.index_path)
        try:
            yield
        finally:
            application.state.index.close()
            application.state.index = None

    application = FastAPI(title="findex — пошукова система", version="0.7.0", lifespan=lifespan)
    application.state.settings = config
    application.state.index = None
    application.state.started_at = time.monotonic()
    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
    templates.env.filters["highlight"] = highlighted_html
    application.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Помилка запиту request_id=%s", request_id)
            response = JSONResponse(status_code=500, content={"detail":"Внутрішня помилка сервера", "request_id":request_id})
        response.headers["X-Request-ID"] = request_id
        logger.info("%s %s %d request_id=%s", request.method, request.url.path, response.status_code, request_id)
        return response

    @application.get("/health")
    def health(request: Request):
        ix = getattr(request.app.state, "index", None)
        if ix is None or ix.is_closed:
            raise HTTPException(status_code=503, detail="Пошуковий індекс недоступний")
        return {"status": "ok"}

    @application.get("/stats", response_model=StatsResponse)
    def stats(index: Annotated[Index, Depends(get_index)], request: Request,
              settings: Annotated[Settings, Depends(get_settings)]):
        return StatsResponse(documents=index.num_docs, vocabulary=len(index), tokens=sum(index.doc_lengths.values()),
                             uptime_seconds=round(time.monotonic()-request.app.state.started_at, 3))

    @application.get("/search", response_model=SearchResponse)
    def search(q: Annotated[str, Query(min_length=1, max_length=200)],
               index: Annotated[Index, Depends(get_index)],
               k: Annotated[int, Query(ge=1, le=100)] = 10,
               scorer: Literal["bm25", "tfidf"] = "bm25",
               page: Annotated[int, Query(ge=1, le=10000)] = 1):
        return query_results(index, q, k, scorer, page)

    @application.get("/docs/{doc_id}", response_model=DocumentResponse)
    def doc_api(doc_id: int, index: Annotated[Index, Depends(get_index)]):
        return get_document(index, doc_id)

    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home(request: Request, index: Annotated[Index, Depends(get_index)],
             q: Annotated[str, Query(max_length=200)] = "",
             k: Annotated[int, Query(ge=1, le=100)] = 10,
             page: Annotated[int, Query(ge=1, le=10000)] = 1,
             scorer: Literal["bm25", "tfidf"] = "bm25"):
        payload = query_results(index, q, k, scorer, page) if q.strip() else None
        return templates.TemplateResponse(request, "index.html", {"data": payload, "q": q, "page": page,
                                                                 "k": k, "scorer": scorer})

    @application.get("/doc/{doc_id}", response_class=HTMLResponse, include_in_schema=False)
    def doc_page(request: Request, doc_id: int, index: Annotated[Index, Depends(get_index)]):
        return templates.TemplateResponse(request, "document.html", {"document": get_document(index, doc_id)})

    return application


app = create_app()
