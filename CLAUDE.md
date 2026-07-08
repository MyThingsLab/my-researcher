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
  out-of-band step). Two side effects, both routed through `Policy` (`Guard`
  default): a committed `research/<topic>.md` / `STUDY-PLAN.md` PR (idempotent
  per topic) and an issue comment. **Never merges.** Ledger `kind`s: `research`
  (brief), `study_plan` (plan).
- **Backlog label:** `my-researcher`
