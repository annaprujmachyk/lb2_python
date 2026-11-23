import json
from pathlib import Path

from typer.testing import CliRunner

from findex.cli import app

RUNNER = CliRunner()


def test_cli_help():
    result = RUNNER.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "search" in result.stdout


def test_cli_commands_end_to_end(corpus: Path, tmp_path: Path):
    target = tmp_path / "indexed.json"
    built = RUNNER.invoke(app, ["index", str(corpus), "--out", str(target)])
    assert built.exit_code == 0, built.output
    assert target.is_file()
    searched = RUNNER.invoke(app, ["search", str(target), "python", "--json"])
    assert searched.exit_code == 0, searched.output
    rows = [json.loads(line) for line in searched.stdout.splitlines()]
    assert len(rows) == 2
    assert all("score" in row for row in rows)
    stats = RUNNER.invoke(app, ["stats", str(target)])
    assert stats.exit_code == 0
    assert "Documents" in stats.output


def test_cli_error_missing_file(tmp_path: Path):
    result = RUNNER.invoke(app, ["search", str(tmp_path / "missing.json"), "python", "--json"])
    assert result.exit_code != 0
    assert "Error:" in result.output


def test_cli_error_malformed_query(corpus: Path, tmp_path: Path):
    target = tmp_path / "index.json"
    RUNNER.invoke(app, ["index", str(corpus), "--out", str(target)])
    result = RUNNER.invoke(app, ["search", str(target), "python OR", "--json"])
    assert result.exit_code != 0
    assert "Error:" in result.output


def test_cli_no_positions(corpus: Path, tmp_path: Path):
    target = tmp_path / "index.json"
    assert RUNNER.invoke(app, ["index", str(corpus), "--out", str(target), "--no-positions"]).exit_code == 0
    result = RUNNER.invoke(app, ["search", str(target), '"quick brown"', "--json"])
    assert result.exit_code != 0
    assert "positions" in result.output
