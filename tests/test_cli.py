from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import make_repo
from myresearcher import cli


def test_cli_brief_noop_degrades_and_prints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = make_repo(tmp_path)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    # Patch the network + gh boundaries at the CLI's Researcher construction.
    from conftest import FakeRunner, fake_fetch

    fake = FakeRunner()
    real_make = cli._make

    def _make(args):  # noqa: ANN001
        r = real_make(args)
        r.runner = fake
        r.github._run = fake
        r.fetch = fake_fetch
        return r

    monkeypatch.setattr(cli, "_make", _make)

    code = cli.main(
        [
            "brief",
            "--issue", "5",
            "--repo", "owner/name",
            "--repo-root", str(repo),
            "--ledger", str(tmp_path / "ledger.jsonl"),
            "--sources", "arxiv",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "success (brief)" in out


def test_cli_requires_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main([])


def test_cli_plan_skips_when_no_topics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "tool": "myresearcher", "kind": "research", "outcome": "success",
                "detail": "", "data": {"topic": "GNN"}, "ts": "2026-01-01T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    code = cli.main(["plan", "--repo-root", str(tmp_path), "--ledger", str(ledger), "--no-pr"])
    out = capsys.readouterr().out
    assert code == 0
    assert "skipped (plan)" in out


def test_noop_placeholder() -> None:
    assert True
