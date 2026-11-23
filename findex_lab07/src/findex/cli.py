"""findex command line interface: index, search, stats."""

import json
import asyncio
import tempfile
import logging
import re
import sys
from enum import Enum
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.text import Text
from rich.table import Table

from findex.parallel import build_parallel_index
from findex.crawler.command import run_crawl
from findex.models import DocMeta
from findex.ranking import BM25, TfIdf, search as run_search
from findex.store import load, save

app = typer.Typer(help="Search text documents with an inverted index and BM25.", no_args_is_help=True)
out = Console()
err = Console(stderr=True)


class ScorerChoice(str, Enum):
    bm25 = "bm25"
    tfidf = "tfidf"



class ExecutorChoice(str, Enum):
    serial = "serial"
    threads = "threads"
    processes = "processes"

@app.callback()
def setup(verbose: int = typer.Option(0, "-v", "--verbose", count=True, help="Increase logging verbosity (-v, -vv).")) -> None:
    level = logging.DEBUG if verbose > 1 else (logging.INFO if verbose else logging.WARNING)
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s", stream=sys.stderr, force=True)


@app.command("index")
def index_command(
    corpus: Path = typer.Argument(..., help="Directory with UTF-8 .txt documents"),
    out_file: Path = typer.Option(..., "--out", help="Output file (.json or .bin)"),
    positions: bool = typer.Option(True, "--positions/--no-positions", help="Store token positions for phrase queries"),
    limit: int | None = typer.Option(None, "--limit", min=0, help="Index at most N documents"),
    workers: int = typer.Option(1, "--workers", min=1, help="Number of workers"),
    executor: ExecutorChoice = typer.Option(ExecutorChoice.serial, "--executor", help="serial, threads or processes"),
    chunk_size: int | None = typer.Option(None, "--chunk-size", min=1),
) -> None:
    try:
        # JSONL corpus is converted incrementally for the existing text indexer.
        if corpus.is_file() and corpus.suffix == '.jsonl':
            with tempfile.TemporaryDirectory(prefix='findex-crawl-') as tmp:
                root = Path(tmp)
                page_meta = {}
                with corpus.open(encoding='utf-8') as stream:
                    for n, line in enumerate(stream):
                        if limit is not None and n >= limit:
                            break
                        page = json.loads(line)
                        page_meta[n] = DocMeta(path=page['url'], title=page.get('title', page['url']))
                        (root / f'{n:08d}.txt').write_text(
                            page.get('title', '') + '\n' + page['text'], encoding='utf-8')
                ix, metrics = build_parallel_index(root, positions=positions,
                    executor=executor.value, workers=workers, chunk_size=chunk_size)
            # Keep URL and page title instead of temporary text filenames.
            ix.doc_meta.update({doc_id: page_meta[int(meta.path.removesuffix('.txt'))] for doc_id, meta in ix.doc_meta.items()})
            save(ix, out_file)
            out.print(f'Indexed {ix.num_docs} crawled pages / {len(ix)} terms → {out_file}')
            return
        with Progress(SpinnerColumn(), TextColumn("Indexing {task.completed} documents"), console=err, transient=True) as progress:
            task_id = progress.add_task("index", total=None)
            ix, metrics = build_parallel_index(
                corpus, positions=positions, limit=limit, executor=executor.value,
                workers=workers, chunk_size=chunk_size, progress=lambda n: progress.advance(task_id, advance=n),
            )
        save(ix, out_file)
    except (OSError, ValueError) as exc:
        err.print(f"Error: {escape(str(exc))}")
        raise typer.Exit(1) from None
    out.print(f"Indexed {ix.num_docs} documents / {len(ix)} terms → {out_file}")
    out.print(f"Executor: {executor.value}, workers: {workers}, wall: {metrics.total_seconds:.3f}s, merge: {metrics.merge_seconds:.3f}s")


@app.command("search")
def search_command(
    index_file: Path = typer.Argument(..., help="Saved index (.json or .bin)"),
    query: str = typer.Argument(..., help='Query, e.g. python AND (async OR await)'),
    k: int = typer.Option(10, "--k", min=0, help="Maximum results"),
    scorer: ScorerChoice = typer.Option(ScorerChoice.bm25, "--scorer"),
    json_output: bool = typer.Option(False, "--json", help="JSON Lines to stdout"),
) -> None:
    try:
        ix = load(index_file)
        results = run_search(ix, query, scorer=BM25() if scorer == ScorerChoice.bm25 else TfIdf(), k=k)
    except (OSError, ValueError, KeyError) as exc:
        err.print(f"Error: {escape(str(exc))}")
        raise typer.Exit(1) from None
    if json_output:
        for result in results:
            sys.stdout.write(json.dumps({"doc_id": result.doc_id, "title": result.title, "score": result.score, "snippet": result.snippet}, ensure_ascii=False) + "\n")
        return
    table = Table(title=f"Results for {query!r} ({len(results)})")
    table.add_column("Doc")
    table.add_column("Score", justify="right")
    table.add_column("Title")
    table.add_column("Snippet")
    for result in results:
        marked = Text()
        for piece in re.split(r"(\[\[.*?\]\])", result.snippet):
            if piece.startswith("[[") and piece.endswith("]]"):
                marked.append(piece[2:-2], style="bold yellow")
            else:
                marked.append(piece)
        table.add_row(str(result.doc_id), f"{result.score:.3f}", escape(result.title), marked)
    out.print(table)


@app.command("stats")
def stats_command(index_file: Path = typer.Argument(..., help="Saved index (.json or .bin)")) -> None:
    try:
        ix = load(index_file)
    except (OSError, ValueError, KeyError) as exc:
        err.print(f"Error: {escape(str(exc))}")
        raise typer.Exit(1) from None
    table = Table(title="Index statistics")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for name, value in (
        ("Documents", str(ix.num_docs)),
        ("Total tokens", str(sum(ix.doc_lengths.values()))),
        ("Vocabulary", str(len(ix))),
        ("Average document length", f"{ix.avg_doc_length:.2f}"),
        ("Token positions stored", str(ix.positions)),
    ):
        table.add_row(name, value)
    out.print(table)
    top = sorted(ix.items(), key=lambda kv: sum(p.tf for p in kv[1]), reverse=True)[:20]
    table2 = Table(title="Most frequent terms")
    table2.add_column("Term")
    table2.add_column("Frequency", justify="right")
    for term, ps in top:
        table2.add_row(escape(term), str(sum(posting.tf for posting in ps)))
    out.print(table2)




@app.command("crawl")
def crawl_command(
    seed_url: str = typer.Argument(..., help="HTTP(S) seed URL on a site you have permission to crawl"),
    max_pages: int = typer.Option(500, "--max-pages", min=0),
    concurrency: int = typer.Option(10, "--concurrency", min=1),
    per_host: int = typer.Option(2, "--per-host", min=1),
    delay: float = typer.Option(0.2, "--delay", min=0),
    out_file: Path = typer.Option(Path("data/crawl.jsonl"), "--out"),
    log_file: Path = typer.Option(Path("crawl.log"), "--log"),
    domain: list[str] | None = typer.Option(None, "--domain", help="Allowed host; repeat option for multiple hosts"),
) -> None:
    """Politely crawl permitted pages into line-delimited JSON."""
    try:
        asyncio.run(run_crawl(seed_url, out_file, max_pages=max_pages,
                              concurrency=concurrency, per_host=per_host,
                              delay=delay, allowed_domains=domain, log_file=log_file))
    except (ValueError, OSError) as exc:
        err.print(f"Error: {escape(str(exc))}")
        raise typer.Exit(1) from None



@app.command("serve")
def serve_command(
    port: int = typer.Option(8000, "--port", min=1, max=65535),
    workers: int = typer.Option(1, "--workers", min=1),
    host: str = typer.Option("127.0.0.1", "--host"),
) -> None:
    """Запустити пошуковий вебсервер FastAPI."""
    import uvicorn
    uvicorn.run("findex.web:app", host=host, port=port, workers=workers)

if __name__ == "__main__":
    app()
