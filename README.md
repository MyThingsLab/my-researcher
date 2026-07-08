# my-researcher

[![CI](https://github.com/MyThingsLab/my-researcher/actions/workflows/ci.yml/badge.svg)](https://github.com/MyThingsLab/my-researcher/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/MyThingsLab/my-researcher/branch/main/graph/badge.svg)](https://codecov.io/gh/MyThingsLab/my-researcher)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![MIT](https://img.shields.io/badge/license-MIT-green)

A [MyThingsLab](../my-things-core) `My[X]` tool: the **discovery + synthesis**
front for studying a topic. Given a topic issue, it discovers external sources
**live** (arXiv + a web-search provider), then makes **one** Engine call to write
a cited study brief — a summary, an annotated reading list, and a
prerequisites/learning path. A second `plan` invocation orders a set of
already-researched topics into a study path.

It complements the rest of the line: **MyKnowledger** *answers* questions from a
corpus a human already built, while MyResearcher *goes and finds* the sources.
It never ingests a corpus itself — it hands you a cited source list you can feed
to graphify out of band.

## Usage

```bash
# Research one topic issue → cited brief, committed as research/<topic>.md (PR)
# and posted as an issue comment.
myresearcher brief --issue 12 --repo MyThingsLab/study --engine claude-cli

# arXiv only, no web provider needed, print locally without a PR/comment:
myresearcher brief --issue 12 --sources arxiv --no-pr --no-comment

# Order every researched topic into a study path → research/STUDY-PLAN.md (PR).
myresearcher plan --repo MyThingsLab/study --engine claude-cli
```

Each invocation makes **exactly one** Engine call. Against the default
`--engine noop` (zero tokens), `brief` emits the raw discovered sources with
their citations and `plan` lists the topics in discovery order — an honest
degrade, never a fabricated brief.

## Retrieval & keys

- **arXiv** is the keyless default (`http://export.arxiv.org/api`).
- **Web search** uses **Tavily**; set `TAVILY_API_KEY` to enable it. Without a
  key, arXiv-only still produces a usable brief. In CI the key is a secret:
  `gh secret set TAVILY_API_KEY -R MyThingsLab/my-researcher`. It is never
  committed.

All retrieval is deterministic, LLM-free HTTP; the network boundary is mocked in
the test suite.

## Install (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ../my-things-core -e ../my-guard -e ".[dev]"
pytest
```

See [`CLAUDE.md`](CLAUDE.md) for the tool's seams and [`HARNESS.md`](HARNESS.md)
for the inherited build rules.

## License

MIT — see [`LICENSE`](LICENSE).
