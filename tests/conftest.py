from __future__ import annotations

import json
from pathlib import Path

import pytest

# Shared fakes come from mythings.testing (plain imports; the aliased fixture
# re-export + getfixturevalue wrapper is the CONVENTIONS.md recipe for a
# conftest that also imports helpers at top level).
from mythings.testing import FakeGh, GitRepo, ScriptedEngine, make_git_repo
from mythings.testing import clean_git_env as _shared_clean_git_env  # noqa: F401
from mythings.testing import fake_fetch as _fake_fetch

from myresearcher.retrieval import TAVILY_ENDPOINT

__all__ = ["ScriptedEngine"]


@pytest.fixture(autouse=True)
def _clean_git_env(request: pytest.FixtureRequest) -> None:
    # Real git worktrees in every test; hook-launched pytest (pre-commit)
    # must not leak GIT_* into them.
    request.getfixturevalue("_shared_clean_git_env")


ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2101.00001v1</id>
    <title>Graph Neural Networks for Physics Simulation</title>
    <summary>We study graph neural networks applied to physical systems.</summary>
    <published>2021-01-01T00:00:00Z</published>
    <author><name>Ada Lovelace</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/1901.00002v2</id>
    <title>A Survey of Message Passing Networks</title>
    <summary>An older survey of neural message passing on graphs.</summary>
    <published>2019-01-01T00:00:00Z</published>
    <author><name>Alan Turing</name></author>
  </entry>
</feed>
"""

TAVILY_JSON = {
    "results": [
        {
            "title": "Distill: A Gentle Introduction to Graph Neural Networks",
            "url": "https://distill.pub/2021/gnn-intro/",
            "content": "An interactive intro to graph neural networks and their uses.",
        }
    ]
}

fake_fetch = _fake_fetch({TAVILY_ENDPOINT: TAVILY_JSON, "export.arxiv.org": ARXIV_ATOM})

empty_fetch = _fake_fetch(
    {TAVILY_ENDPOINT: {"results": []}},
    default=b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>',
)


def fake_gh(
    *,
    title: str = "Graph Neural Networks",
    body: str = "GNNs for physics",
    existing_pr: dict | None = None,
    open_bibliography_issues: list[dict] | None = None,
) -> FakeGh:
    issues = open_bibliography_issues or []
    state = {"next_issue": 100}

    def issue_view(argv: list[str]) -> str:
        return json.dumps({"number": int(argv[2]), "title": title, "body": body})

    def issue_list(argv: list[str]) -> str:
        return json.dumps(
            [
                {
                    "number": i["number"],
                    "title": i["title"],
                    "body": i.get("body", ""),
                    "labels": [{"name": "my-bibliography"}],
                    "url": f"https://github.com/owner/name/issues/{i['number']}",
                }
                for i in issues
            ]
        )

    def issue_create(argv: list[str]) -> str:
        state["next_issue"] += 1
        return f"https://github.com/owner/name/issues/{state['next_issue']}\n"

    return FakeGh(
        {
            ("issue", "view"): issue_view,
            ("pr", "list"): json.dumps([existing_pr] if existing_pr else []),
            ("pr", "create"): "https://github.com/owner/name/pull/7\n",
            ("issue", "comment"): "https://github.com/owner/name/issues/5#issuecomment-1\n",
            ("issue", "list"): issue_list,
            ("issue", "create"): issue_create,
            ("issue", "edit"): "",
        }
    )


def make_repo(tmp_path: Path) -> Path:
    return make_git_repo(tmp_path, files={"README.md": "# study\n"}).path


def branch_file(repo: Path, branch: str, path: str) -> str:
    return GitRepo(path=repo, origin=repo.parent / "origin.git").read_committed(branch, path)
