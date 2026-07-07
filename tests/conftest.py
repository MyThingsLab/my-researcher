from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from mythings.engine import EngineRequest, EngineResult

from myresearcher.retrieval import TAVILY_ENDPOINT


@pytest.fixture(autouse=True)
def _clean_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # pre-commit runs hooks with GIT_DIR/GIT_INDEX_FILE set; they leak into the
    # git subprocesses these tests spawn (and into isolation.Workspace) and break
    # worktree ops on the throwaway repo. Real runs are not inside a hook.
    for var in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY"):
        monkeypatch.delenv(var, raising=False)


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


def fake_fetch(url: str, *, data: bytes | None = None, headers: dict | None = None) -> bytes:
    if url == TAVILY_ENDPOINT:
        return json.dumps(TAVILY_JSON).encode()
    if "export.arxiv.org" in url:
        return ARXIV_ATOM.encode()
    raise AssertionError(f"unexpected fetch url: {url}")


def empty_fetch(url: str, *, data: bytes | None = None, headers: dict | None = None) -> bytes:
    if url == TAVILY_ENDPOINT:
        return json.dumps({"results": []}).encode()
    return b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'


class ScriptedEngine:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[EngineRequest] = []

    def run(self, request: EngineRequest) -> EngineResult:
        self.calls.append(request)
        return EngineResult(text=self.reply)


class SpyEngine:
    def __init__(self) -> None:
        self.calls: list[EngineRequest] = []

    def run(self, request: EngineRequest) -> EngineResult:
        self.calls.append(request)
        return EngineResult(text="")


class FakeRunner:
    # Mocks only the `gh` subprocess boundary.
    def __init__(
        self,
        *,
        title: str = "Graph Neural Networks",
        body: str = "GNNs for physics",
        existing_pr: dict | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self.title = title
        self.body = body
        self.existing_pr = existing_pr

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        if argv[:2] == ["issue", "view"]:
            return json.dumps({"number": int(argv[2]), "title": self.title, "body": self.body})
        if argv[:2] == ["pr", "list"]:
            return json.dumps([self.existing_pr] if self.existing_pr else [])
        if argv[:2] == ["pr", "create"]:
            return "https://github.com/owner/name/pull/7\n"
        if argv[:2] == ["issue", "comment"]:
            return "https://github.com/owner/name/issues/5#issuecomment-1\n"
        raise AssertionError(f"unexpected gh call: {argv}")


def make_repo(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    repo = tmp_path / "work"
    repo.mkdir()
    (repo / "README.md").write_text("# study\n", encoding="utf-8")

    def _git(*argv: str) -> None:
        subprocess.run(["git", "-C", str(repo), *argv], check=True, capture_output=True, text=True)

    _git("init", "-b", "main")
    _git("config", "user.email", "t@example.com")
    _git("config", "user.name", "Researcher")
    _git("add", "-A")
    _git("commit", "-m", "init")
    _git("remote", "add", "origin", str(origin))
    _git("push", "-u", "origin", "main")
    return repo


def branch_file(repo: Path, branch: str, path: str) -> str:
    origin = repo.parent / "origin.git"
    proc = subprocess.run(
        ["git", "-C", str(origin), "show", f"{branch}:{path}"],
        capture_output=True,
        text=True,
    )
    return proc.stdout
