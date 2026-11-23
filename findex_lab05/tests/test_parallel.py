from pathlib import Path
import json
import pytest
from typer.testing import CliRunner

from findex.cli import app
from findex.index import build_index
from findex.parallel import build_parallel_index, build_partial, merge
from findex.store import _to_json


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / 'docs'
    root.mkdir()
    for i, text in enumerate(['Python Python async', 'JavaScript python', 'hello world', 'café résumé Python', '', '😀 Unicode']):
        (root / f'{i}.txt').write_text(text, encoding='utf-8')
    return root


@pytest.mark.parametrize('engine,workers', [
    ('serial',1), ('threads',1), ('threads',2), ('threads',4),
    ('processes',1), ('processes',2), ('processes',4),
])
def test_build_byte_identical(corpus: Path, engine: str, workers: int) -> None:
    baseline = build_index(corpus)
    result, metrics = build_parallel_index(corpus, executor=engine, workers=workers, chunk_size=2)
    assert json.dumps(_to_json(baseline),ensure_ascii=False) == json.dumps(_to_json(result),ensure_ascii=False)
    assert metrics.merge_seconds >= 0


def test_no_positions(corpus: Path) -> None:
    baseline = build_index(corpus, positions=False)
    ix, _ = build_parallel_index(corpus, executor='processes', workers=2, positions=False, chunk_size=1)
    assert _to_json(ix) == _to_json(baseline)


def test_empty(tmp_path: Path) -> None:
    ix, _ = build_parallel_index(tmp_path, executor='processes', workers=2)
    assert ix.num_docs == 0


def test_duplicate_ids_rejected(corpus: Path) -> None:
    paths = list(corpus.glob('*.txt'))
    part = build_partial(paths[:1], root=corpus)
    with pytest.raises(ValueError, match='Overlapping'):
        merge([part, part], source_root=corpus)


def test_invalid_arguments(corpus: Path) -> None:
    with pytest.raises(ValueError):
        build_parallel_index(corpus, workers=0)
    with pytest.raises(ValueError):
        build_parallel_index(corpus, limit=-1)
    with pytest.raises(ValueError):
        build_parallel_index(corpus, chunk_size=0)


def test_cli_parallel(corpus: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    target = tmp_path / 'out.json'
    result = runner.invoke(app,['index',str(corpus),'--out',str(target),'--executor','processes','--workers','2'])
    assert result.exit_code == 0, result.output
    assert target.exists()
    result = runner.invoke(app,['search',str(target),'python'])
    assert result.exit_code == 0, result.output


def test_worker_exception_propagation(monkeypatch: pytest.MonkeyPatch, corpus: Path) -> None:
    from findex import parallel
    def fail(_):
        raise RuntimeError('worker exploded')
    monkeypatch.setattr(parallel, '_worker',fail)
    with pytest.raises(RuntimeError, match='worker exploded'):
        build_parallel_index(corpus, executor='serial')
