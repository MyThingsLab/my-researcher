from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from myguard import Guard
from mythings.engine import Engine, NoopEngine
from mythings.github import GitHub, GitHubError, PullRequest, Runner, _gh, _pr_number
from mythings.isolation import Workspace, in_github_actions
from mythings.ledger import Ledger
from mythings.policy import Action, Decision, Policy

from myresearcher.retrieval import Fetcher, Source, _http, retrieve
from myresearcher.synthesis import (
    Brief,
    render_brief,
    render_plan,
    synthesize_brief,
    synthesize_plan,
)

LABEL = "my-researcher"
BIBLIOGRAPHY_LABEL = "my-bibliography"


class PolicyDenied(RuntimeError):
    pass


@dataclass(frozen=True)
class Result:
    outcome: str  # success | skipped | failure
    mode: str  # brief | plan
    topic: str | None
    pr: int | None
    detail: str
    path: str | None = None


@dataclass(frozen=True)
class _Topic:
    number: int
    title: str
    body: str


def _slug(text: str) -> str:
    out = []
    for ch in text.lower().strip():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")[:60] or "topic"


class Researcher:
    def __init__(
        self,
        *,
        repo_root: str | Path = ".",
        repo: str | None = None,
        ledger: Ledger,
        base: str = "main",
        engine: Engine | None = None,
        policy: Policy | None = None,
        runner: Runner = _gh,
        fetch: Fetcher = _http,
        web_api_key: str | None = None,
        sources: tuple[str, ...] = ("arxiv", "web"),
        top: int = 15,
        level: str = "standard",
    ) -> None:
        self.repo_root = Path(repo_root)
        self.repo = repo
        self.ledger = ledger
        self.base = base
        self.engine: Engine = engine or NoopEngine()
        self.policy: Policy = policy or Guard()
        self.runner = runner
        self.github = GitHub(repo, runner=runner)
        self.fetch = fetch
        self.web_api_key = web_api_key
        self.sources = sources
        self.top = top
        self.level = level

    # ---- brief -----------------------------------------------------------

    def brief(
        self,
        issue: int,
        *,
        no_pr: bool = False,
        no_comment: bool = False,
        no_bibliography: bool = False,
    ) -> Result:
        try:
            topic = self._fetch_issue(issue)
        except GitHubError as err:
            return self._fail("brief", None, f"could not read issue #{issue}: {err}")

        found = retrieve(
            topic.title,
            topic.body,
            sources=self.sources,
            top=self.top,
            fetch=self.fetch,
            api_key=self.web_api_key,
        )
        if not found:
            detail = f"no sources found for {topic.title!r}"
            url = None if no_comment else self._comment(issue, f"_{detail}_")
            self._record_brief("skipped", topic, None, None, None, comment_url=url)
            return self._skip("brief", topic.title, detail)

        brief = synthesize_brief(self.engine, topic.title, topic.body, found, level=self.level)
        markdown = render_brief(brief)

        pr = None
        path = f"research/{_slug(topic.title)}.md"
        if not no_pr:
            try:
                pr = self._open_pr_with_file(
                    path,
                    markdown,
                    branch=f"{LABEL}/{issue}",
                    commit=f"research: brief for {topic.title}",
                    title=f"research: {topic.title}",
                    body=f"Study brief for `{topic.title}`.\n\nCloses #{issue}.",
                )
            except PolicyDenied as denied:
                return self._fail("brief", topic.title, str(denied))

        bibliography_issues = (
            [] if no_bibliography else self._file_bibliography_issues(topic, brief)
        )

        url = None if no_comment else self._comment(issue, markdown)
        self._record_brief(
            "success",
            topic,
            brief,
            pr.number if pr else None,
            path,
            comment_url=url,
            bibliography_issues=bibliography_issues,
        )
        detail = f"brief for {topic.title!r} ({len(found)} sources)"
        if bibliography_issues:
            detail += f", filed {len(bibliography_issues)} bibliography issue(s)"
        return Result("success", "brief", topic.title, pr.number if pr else None, detail, path)

    # ---- plan ------------------------------------------------------------

    def plan(self, *, no_pr: bool = False) -> Result:
        topics = self._researched_topics()
        if len(topics) < 2:
            return self._skip("plan", None, f"only {len(topics)} researched topic(s) to order")

        study = synthesize_plan(self.engine, topics)
        markdown = render_plan(study)

        pr = None
        path = "research/STUDY-PLAN.md"
        if not no_pr:
            try:
                pr = self._open_pr_with_file(
                    path,
                    markdown,
                    branch=f"{LABEL}/study-plan",
                    commit="research: study plan",
                    title="research: study plan",
                    body=f"Study path over {len(topics)} researched topics.",
                )
            except PolicyDenied as denied:
                return self._fail("plan", None, str(denied))

        self.ledger.record(
            tool="myresearcher",
            kind="study_plan",
            outcome="success",
            detail=f"study path over {len(topics)} topics",
            topics=[name for name, _ in topics],
            steps=[s.topic for s in study.steps],
            plan_path=path,
            pr=pr.number if pr else None,
        )
        return Result("success", "plan", None, pr.number if pr else None,
                      f"study path over {len(topics)} topics", path)

    def _researched_topics(self) -> list[tuple[str, str]]:
        latest: dict[str, tuple[str, str]] = {}
        for entry in self.ledger.read(tool="myresearcher", kind="research"):
            if entry.outcome != "success":
                continue
            topic = entry.data.get("topic")
            if topic:
                latest[topic] = (topic, entry.data.get("summary", ""))
        return [latest[k] for k in sorted(latest)]

    # ---- github / git helpers -------------------------------------------

    def _fetch_issue(self, number: int) -> _Topic:
        argv = ["issue", "view", str(number), "--json", "number,title,body"]
        if self.repo:
            argv += ["--repo", self.repo]
        obj = json.loads(self.runner(argv))
        return _Topic(number=obj["number"], title=obj["title"], body=obj.get("body") or "")

    def _open_pr_with_file(
        self, path: str, content: str, *, branch: str, commit: str, title: str, body: str
    ) -> PullRequest:
        existing = self._existing_pr(branch)
        with Workspace(self.repo_root, self.base) as tree:
            self._git(tree, ["checkout", "-B", branch])
            target = tree / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            self._git(tree, ["add", path])
            self._git(tree, ["commit", "-m", commit])
            if existing is None:
                self._git(tree, ["push", "-u", "origin", branch])
            else:
                # Reuse the open PR; refresh its branch without a force so Guard's
                # force-push rule never fires (fast-forward from base + one commit).
                self._git(tree, ["push", "origin", branch])
        if existing is not None:
            return existing
        self._guard(f"gh pr create --head {branch} --base {self.base}")
        return self.github.open_pr(title=title, body=body, base=self.base, head=branch)

    def _existing_pr(self, branch: str) -> PullRequest | None:
        argv = ["pr", "list", "--head", branch, "--state", "open", "--json", "number,url"]
        if self.repo:
            argv += ["--repo", self.repo]
        rows = json.loads(self.runner(argv))
        if not rows:
            return None
        row = rows[0]
        return PullRequest(number=row.get("number") or _pr_number(row["url"]), url=row["url"])

    def _file_bibliography_issues(self, topic: _Topic, brief: Brief) -> list[dict]:
        # Every arXiv source actually cited in the brief already carries a
        # locator my-bibliography understands verbatim (Source.source_id is
        # "arxiv:<id>"). Web sources have no resolvable DOI/arXiv id, so they
        # are left uncataloged. Filed as a plain labeled issue, not a package
        # call -- my-bibliography is a fully independent tool, same fence as
        # MyTodo reading MyPlanner's ledger instead of importing it.
        if self.repo is None:
            return []
        smap: dict[str, Source] = {s.source_id: s for s in brief.sources}
        existing_titles: set[str] | None = None
        filed: list[dict] = []
        for source_id in brief.cited:
            source = smap.get(source_id)
            if source is None or source.origin != "arxiv":
                continue
            title = f"bibliography: catalog {source_id}"
            if existing_titles is None:
                existing_titles = self._open_bibliography_titles()
            if title in existing_titles:
                continue
            action = Action(kind="bash", payload={"command": f"gh issue create --title {title!r}"})
            gate = self.policy.evaluate(action).under(unattended=in_github_actions())
            if gate is not Decision.ALLOW:
                continue
            body = (
                f"{source_id}\n\nCited in the {topic.title!r} study brief "
                f"(issue #{topic.number})."
            )
            created = self.github.create_issue(title=title, body=body)
            self.github.add_labels(created.number, [BIBLIOGRAPHY_LABEL])
            filed.append({"source_id": source_id, "issue": created.number})
        return filed

    def _open_bibliography_titles(self) -> set[str]:
        try:
            issues = self.github.list_issues(labels=[BIBLIOGRAPHY_LABEL], state="open", limit=100)
        except GitHubError:
            return set()
        return {i.title for i in issues}

    def _comment(self, issue: int, body: str) -> str | None:
        if self.repo is None:
            return None
        argv = ["issue", "comment", str(issue), "--repo", self.repo, "--body", body]
        action = Action(kind="bash", payload={"command": f"gh issue comment {issue}"})
        if self.policy.evaluate(action).under(unattended=in_github_actions()) is not Decision.ALLOW:
            return None
        return self.runner(argv).strip() or None

    def _git(self, tree: Path, argv: list[str]) -> None:
        self._guard("git " + " ".join(argv))
        proc = subprocess.run(["git", "-C", str(tree), *argv], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(argv)} failed: {proc.stderr.strip()}")

    def _guard(self, command: str) -> None:
        result = self.policy.evaluate(Action(kind="bash", payload={"command": command}))
        if result.under(unattended=in_github_actions()) is not Decision.ALLOW:
            raise PolicyDenied(f"policy blocked: {command} ({result.reason or result.decision})")

    # ---- ledger / results ------------------------------------------------

    def _record_brief(
        self,
        outcome: str,
        topic: _Topic,
        brief: Brief | None,
        pr: int | None,
        path: str | None,
        *,
        comment_url: str | None,
        bibliography_issues: list[dict] | None = None,
    ) -> None:
        self.ledger.record(
            tool="myresearcher",
            kind="research",
            outcome=outcome,
            detail=f"brief for {topic.title}",
            topic=topic.title,
            issue=topic.number,
            summary=brief.summary if brief else "",
            cited=brief.cited if brief else [],
            sources=[s.source_id for s in brief.sources] if brief else [],
            brief_path=path,
            pr=pr,
            comment_url=comment_url,
            bibliography_issues=bibliography_issues or [],
        )

    def _skip(self, mode: str, topic: str | None, detail: str) -> Result:
        return Result("skipped", mode, topic, None, detail)

    def _fail(self, mode: str, topic: str | None, detail: str) -> Result:
        self.ledger.record(
            tool="myresearcher", kind=mode, outcome="failure", detail=detail, topic=topic
        )
        return Result("failure", mode, topic, None, detail)
