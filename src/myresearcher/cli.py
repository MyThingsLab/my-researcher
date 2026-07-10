from __future__ import annotations

import argparse
import os
from pathlib import Path

from mythings.engine import ClaudeCLIEngine, Engine, NoopEngine
from mythings.ledger import Ledger

from myresearcher.researcher import Researcher, Result


def build_engine(name: str, *, model: str | None = None) -> Engine:
    if name == "claude-cli":
        return ClaudeCLIEngine(model=model)
    return NoopEngine()


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", help="GitHub slug owner/name (defaults to the local remote)")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="local git repo")
    parser.add_argument("--base", default="main", help="base branch for the PR")
    parser.add_argument("--ledger", type=Path, default=Path(".mythings/ledger.jsonl"))
    parser.add_argument("--no-pr", action="store_true", help="skip the committed research PR")
    parser.add_argument(
        "--engine",
        choices=("noop", "claude-cli"),
        default="noop",
        help="Engine backend for synthesis (default: noop — emits the raw source list)",
    )
    parser.add_argument("--engine-model", help="model for --engine claude-cli")


def _render(result: Result) -> str:
    line = f"{result.outcome} ({result.mode}): {result.detail}"
    if result.pr is not None:
        line += f" — PR #{result.pr}"
    if result.path and result.outcome == "success":
        line += f" [{result.path}]"
    return line


def _make(args: argparse.Namespace) -> Researcher:
    return Researcher(
        repo_root=args.repo_root,
        repo=args.repo,
        ledger=Ledger(args.ledger),
        base=args.base,
        engine=build_engine(args.engine, model=args.engine_model),
        web_api_key=os.environ.get("TAVILY_API_KEY"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="myresearcher",
        description="Discover sources for a topic, write a cited study brief, order topics.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    brief = sub.add_parser("brief", help="research one topic issue into a cited brief")
    _add_common(brief)
    brief.add_argument("--issue", type=int, required=True, help="the topic issue to research")
    brief.add_argument(
        "--sources",
        default="arxiv,web",
        help="comma-separated retrieval backends (default: arxiv,web)",
    )
    brief.add_argument("--top", type=int, default=15, help="max sources to shortlist")
    brief.add_argument(
        "--level",
        choices=("standard", "graduate", "research"),
        default="standard",
        help="depth of the synthesized brief (default: standard)",
    )
    brief.add_argument("--no-comment", action="store_true", help="skip the issue comment")
    brief.add_argument(
        "--no-bibliography",
        action="store_true",
        help="skip filing my-bibliography issues for cited arXiv sources",
    )

    plan = sub.add_parser("plan", help="order all researched topics into a study path")
    _add_common(plan)

    args = parser.parse_args(argv)
    researcher = _make(args)

    if args.cmd == "brief":
        researcher.sources = tuple(s.strip() for s in args.sources.split(",") if s.strip())
        researcher.top = args.top
        researcher.level = args.level
        result = researcher.brief(
            args.issue,
            no_pr=args.no_pr,
            no_comment=args.no_comment,
            no_bibliography=args.no_bibliography,
        )
    else:
        result = researcher.plan(no_pr=args.no_pr)

    print(_render(result))
    return 1 if result.outcome == "failure" else 0


if __name__ == "__main__":
    raise SystemExit(main())
