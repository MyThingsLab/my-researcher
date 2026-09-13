# my-researcher — agent instructions

You are developing **my-researcher**, a MyThingsLab My[X] tool.

**Inherited rules:** obey [`./HARNESS.md`](./HARNESS.md) in full — the vendored
MyThingsLab build-harness rules. Do not restate or override them. Anything not
covered here defers to `HARNESS.md`, then `my-things-core/docs/CONVENTIONS.md`.

## This tool

- **Purpose:** given a topic issue, discovers external sources **live** (web
  search + arXiv) via LLM-free HTTP, then writes a cited study brief (summary +
  annotated reading list + prerequisites/learning path); a second `plan`
  invocation orders a set of researched topics into a study path.
- **The single Engine call:** one per invocation. `brief`: "from these
  discovered sources, write a study brief for this topic" → `{summary,
  reading_list, prerequisites, learning_path}`, citing only the given
  `source_id`s. `plan`: "order these already-researched topics into a study
  path" → `{study_path, flags}`. Against `NoopEngine`, `brief` emits the raw
  cited source list and `plan` emits topics in issue order — honest degrade, no
  synthesis.
- **Invariants / rules:** exactly one Engine call per run; all retrieval is
  deterministic, LLM-free HTTP (arXiv keyless default; the web provider — Tavily
  — needs `TAVILY_API_KEY`, a CI secret, never committed). The HTTP boundary is
  mocked in the default suite; any real-network test is `@pytest.mark.slow`.
  **Never ingests a corpus itself** (no graphify ingest — that stays a human,
  out-of-band step). Three side effects, all routed through `Policy` (`Guard`
  default): a committed `research/<topic>.md` / `STUDY-PLAN.md` PR (idempotent
  per topic), an issue comment, and (per `brief`, opt-out `--no-bibliography`)
  filing one `my-bibliography`-labeled issue per cited arXiv source (body is
  the bare `arxiv:<id>` locator, deduped against currently-open bibliography
  issues by title) — never a package import of `mybibliography`, and never a
  call to it; it only leaves a labeled issue for that independent tool to pick
  up. Web-origin sources have no resolvable locator and are never filed.
  **Never merges.** Ledger `kind`s: `research` (brief; `data.bibliography_issues`
  lists what was filed), `study_plan` (plan).
- **Backlog label:** `my-researcher`
