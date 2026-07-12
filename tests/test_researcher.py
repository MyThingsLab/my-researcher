from __future__ import annotations

import json
from pathlib import Path

from mythings.ledger import Ledger

from conftest import (
    ScriptedEngine,
    branch_file,
    empty_fetch,
    fake_fetch,
    fake_gh,
    make_repo,
)
from myresearcher.researcher import Researcher

_BRIEF_REPLY = json.dumps(
    {
        "summary": "GNNs operate on graph-structured data.",
        "reading_list": [{"source_id": "arxiv:2101.00001v1", "why": "core paper", "order": 1}],
        "prerequisites": ["linear algebra"],
        "learning_path": ["basics", "message passing"],
    }
)


def _researcher(repo: Path, tmp_path: Path, fake: fake_gh, **kw) -> tuple[Researcher, Ledger]:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    r = Researcher(
        repo_root=repo,
        repo="owner/name",
        ledger=ledger,
        runner=fake,
        fetch=fake_fetch,
        web_api_key="k",
        **kw,
    )
    return r, ledger


def test_brief_happy_path_opens_pr_and_comments(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    fake = fake_gh()
    r, ledger = _researcher(repo, tmp_path, fake, engine=ScriptedEngine(_BRIEF_REPLY))

    result = r.brief(issue=5)

    assert result.outcome == "success"
    assert result.pr == 7
    assert result.path == "research/graph-neural-networks.md"
    assert any(c[:2] == ["pr", "create"] for c in fake.calls)
    assert any(c[:2] == ["issue", "comment"] for c in fake.calls)

    committed = branch_file(repo, "my-researcher/5", "research/graph-neural-networks.md")
    assert "GNNs operate on graph-structured data." in committed
    assert "arxiv:2101.00001v1" in committed

    entry = list(ledger)[0]
    assert entry.kind == "research"
    assert entry.outcome == "success"
    assert entry.data["topic"] == "Graph Neural Networks"
    assert entry.data["pr"] == 7
    assert entry.data["summary"] == "GNNs operate on graph-structured data."


def test_brief_no_sources_skips_engine_and_pr(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    fake = fake_gh()
    spy = ScriptedEngine()
    r, ledger = _researcher(repo, tmp_path, fake, engine=spy)
    r.fetch = empty_fetch

    result = r.brief(issue=5)

    assert result.outcome == "skipped"
    assert spy.calls == []  # engine never called when nothing was found
    assert not any(c[:2] == ["pr", "create"] for c in fake.calls)  # no PR
    assert any(c[:2] == ["issue", "comment"] for c in fake.calls)  # "no sources" comment
    assert list(ledger)[0].outcome == "skipped"


def test_brief_no_pr_and_no_comment(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    fake = fake_gh()
    r, _ = _researcher(repo, tmp_path, fake, engine=ScriptedEngine(_BRIEF_REPLY))

    result = r.brief(issue=5, no_pr=True, no_comment=True)

    assert result.outcome == "success"
    assert result.pr is None
    assert not any(c[:2] == ["pr", "create"] for c in fake.calls)
    assert not any(c[:2] == ["issue", "comment"] for c in fake.calls)


def test_brief_reuses_existing_pr(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    fake = fake_gh(
        existing_pr={"number": 42, "url": "https://github.com/owner/name/pull/42"}
    )
    r, _ = _researcher(repo, tmp_path, fake, engine=ScriptedEngine(_BRIEF_REPLY))

    result = r.brief(issue=5, no_comment=True)

    assert result.pr == 42  # reused, not newly created
    assert not any(c[:2] == ["pr", "create"] for c in fake.calls)


def test_brief_files_bibliography_issue_for_cited_arxiv_source(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    fake = fake_gh()
    r, ledger = _researcher(repo, tmp_path, fake, engine=ScriptedEngine(_BRIEF_REPLY))

    result = r.brief(issue=5, no_pr=True, no_comment=True)

    assert result.outcome == "success"
    creates = [c for c in fake.calls if c[:2] == ["issue", "create"]]
    assert len(creates) == 1
    assert "bibliography: catalog arxiv:2101.00001v1" in creates[0]
    edits = [c for c in fake.calls if c[:2] == ["issue", "edit"]]
    assert edits and "my-bibliography" in edits[0]

    entry = list(ledger)[0]
    assert entry.data["bibliography_issues"] == [
        {"source_id": "arxiv:2101.00001v1", "issue": 101}
    ]


def test_brief_does_not_file_bibliography_issue_for_web_source(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    fake = fake_gh()
    reply = json.dumps(
        {
            "summary": "An intro to GNNs.",
            "reading_list": [{"source_id": "web:1", "why": "gentle intro", "order": 1}],
            "prerequisites": [],
            "learning_path": [],
        }
    )
    r, ledger = _researcher(repo, tmp_path, fake, engine=ScriptedEngine(reply))

    result = r.brief(issue=5, no_pr=True, no_comment=True)

    assert result.outcome == "success"
    assert not any(c[:2] == ["issue", "create"] for c in fake.calls)
    assert list(ledger)[0].data["bibliography_issues"] == []


def test_brief_no_bibliography_flag_skips_filing(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    fake = fake_gh()
    r, ledger = _researcher(repo, tmp_path, fake, engine=ScriptedEngine(_BRIEF_REPLY))

    result = r.brief(issue=5, no_pr=True, no_comment=True, no_bibliography=True)

    assert result.outcome == "success"
    assert not any(c[:2] == ["issue", "create"] for c in fake.calls)
    assert list(ledger)[0].data["bibliography_issues"] == []


def test_brief_does_not_refile_existing_bibliography_issue(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    fake = fake_gh(
        open_bibliography_issues=[
            {"number": 42, "title": "bibliography: catalog arxiv:2101.00001v1"}
        ]
    )
    r, ledger = _researcher(repo, tmp_path, fake, engine=ScriptedEngine(_BRIEF_REPLY))

    result = r.brief(issue=5, no_pr=True, no_comment=True)

    assert result.outcome == "success"
    assert not any(c[:2] == ["issue", "create"] for c in fake.calls)
    assert list(ledger)[0].data["bibliography_issues"] == []


def test_plan_orders_researched_topics(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    fake = fake_gh()
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.record("myresearcher", "research", "success", topic="GNN", summary="graphs")
    ledger.record("myresearcher", "research", "success", topic="RBM", summary="energy models")

    reply = json.dumps(
        {
            "study_path": [
                {"topic": "RBM", "rationale": "foundational", "prereqs": []},
                {"topic": "GNN", "rationale": "later", "prereqs": ["RBM"]},
            ],
            "flags": [],
        }
    )
    r = Researcher(
        repo_root=repo, repo="owner/name", ledger=ledger, runner=fake,
        fetch=fake_fetch, engine=ScriptedEngine(reply),
    )
    result = r.plan()

    assert result.outcome == "success"
    assert result.pr == 7
    committed = branch_file(repo, "my-researcher/study-plan", "research/STUDY-PLAN.md")
    assert "1. **RBM**" in committed and "2. **GNN**" in committed

    plan_entry = [e for e in ledger if e.kind == "study_plan"][0]
    assert plan_entry.data["steps"] == ["RBM", "GNN"]


def test_plan_skips_with_fewer_than_two_topics(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    fake = fake_gh()
    spy = ScriptedEngine()
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.record("myresearcher", "research", "success", topic="GNN", summary="graphs")
    r = Researcher(
        repo_root=repo, repo="owner/name", ledger=ledger, runner=fake,
        fetch=fake_fetch, engine=spy,
    )

    result = r.plan()

    assert result.outcome == "skipped"
    assert spy.calls == []
    assert not any(c[:2] == ["pr", "create"] for c in fake.calls)
