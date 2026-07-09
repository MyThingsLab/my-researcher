from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from mythings.engine import Engine, EngineRequest

from myresearcher.retrieval import Source

_BRIEF_SYSTEM = (
    "You are a study-brief writer for a technical learner. Ground every claim "
    "ONLY in the numbered sources you are given -- never invent a source, a "
    "result, or a citation. Cite sources by their exact source_id. Prefer the "
    "most foundational and the most recent sources when recommending a reading "
    "order. Reply with a single JSON object and nothing else."
)

_LEVEL_GUIDANCE = {
    "standard": "",
    "graduate": (
        " Write for a graduate-level reader: assume the field's standard "
        "prerequisites rather than re-deriving them, foreground open problems "
        "and where the sources disagree or the theory is unsettled, and "
        "distinguish foundational results from recent/speculative ones."
    ),
    "research": (
        " Write for a research-level reader already fluent in the subfield's "
        "language: skip introductory framing entirely, foreground open "
        "problems and active controversies among the sources, and distinguish "
        "established results from recent/speculative ones."
    ),
}


def _brief_system(level: str) -> str:
    return _BRIEF_SYSTEM + _LEVEL_GUIDANCE.get(level, "")

_PLAN_SYSTEM = (
    "You order a set of already-researched study topics into a learning "
    "sequence, based only on the topic summaries you are given. Put "
    "prerequisites before the topics that depend on them. Never invent a topic "
    "outside the given set. Reply with a single JSON object and nothing else."
)


@dataclass(frozen=True)
class ReadingItem:
    source_id: str
    why: str
    order: int


@dataclass(frozen=True)
class Brief:
    topic: str
    summary: str
    reading_list: list[ReadingItem]
    prerequisites: list[str]
    learning_path: list[str]
    sources: list[Source]
    cited: list[str]
    degraded: bool


@dataclass(frozen=True)
class StudyStep:
    topic: str
    rationale: str
    prereqs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StudyPlan:
    steps: list[StudyStep]
    flags: list[str]
    degraded: bool


def _parse_json_object(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(lines).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    # Models sometimes wrap the JSON in a sentence of preamble or trailing
    # commentary despite the "nothing else" instruction -- retry on just the
    # outermost {...} span before giving up and degrading.
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


_ARXIV_VERSION = re.compile(r"v\d+$")
_BARE_ARXIV_ID = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")


def _normalize_source_id(sid: str) -> str:
    # Models routinely cite arXiv IDs without the version suffix (or without
    # the "arxiv:" prefix) even when the source list spells out both — match
    # on the normalized form so a real citation isn't dropped as invented.
    sid = sid.strip().lower()
    if _BARE_ARXIV_ID.match(sid):
        sid = f"arxiv:{sid}"
    prefix, sep, rest = sid.partition(":")
    if prefix == "arxiv" and sep:
        rest = _ARXIV_VERSION.sub("", rest)
        return f"arxiv:{rest}"
    return sid


def _brief_prompt(title: str, body: str, sources: list[Source]) -> str:
    lines = [f"Topic: {title}"]
    if body.strip():
        lines.append(f"Details: {body.strip()}")
    lines.append("\nSources:")
    for src in sources:
        meta = ", ".join(filter(None, [src.origin, str(src.year) if src.year else ""]))
        lines.append(f"- [{src.source_id}] ({meta}) {src.title}\n  {src.snippet[:500]}")
    lines.append(
        "\nReturn JSON with keys: "
        '"summary" (string, 2-4 sentences), '
        '"reading_list" (array of {"source_id","why","order"}, order starting at 1), '
        '"prerequisites" (array of strings), '
        '"learning_path" (array of strings, the ordered steps to learn this topic). '
        "Only cite source_ids from the list above."
    )
    return "\n".join(lines)


def _raw_brief(topic: str, sources: list[Source]) -> Brief:
    # Honest degrade: no synthesis, just the discovered sources as an ordered
    # reading list citing themselves. Used against NoopEngine or an unparseable
    # reply -- still a usable result, never a fabricated one.
    reading = [
        ReadingItem(source_id=s.source_id, why=(s.snippet[:200] or s.title), order=i)
        for i, s in enumerate(sources, start=1)
    ]
    return Brief(
        topic=topic,
        summary="",
        reading_list=reading,
        prerequisites=[],
        learning_path=[],
        sources=sources,
        cited=[s.source_id for s in sources],
        degraded=True,
    )


def synthesize_brief(
    engine: Engine, title: str, body: str, sources: list[Source], *, level: str = "standard"
) -> Brief:
    reply = engine.run(
        EngineRequest(
            system=_brief_system(level),
            prompt=_brief_prompt(title, body, sources),
            context={"source_count": len(sources)},
        )
    )
    obj = _parse_json_object(reply.text)
    if obj is None:
        return _raw_brief(title, sources)

    by_norm = {_normalize_source_id(s.source_id): s.source_id for s in sources}
    reading: list[ReadingItem] = []
    for i, item in enumerate(obj.get("reading_list") or [], start=1):
        if not isinstance(item, dict):
            continue
        sid = str(item.get("source_id", "")).strip()
        actual_sid = by_norm.get(_normalize_source_id(sid))
        if actual_sid is None:  # drop any source the model invented
            continue
        order = item.get("order")
        reading.append(
            ReadingItem(
                source_id=actual_sid,
                why=str(item.get("why", "")).strip(),
                order=int(order) if isinstance(order, int) else i,
            )
        )
    reading.sort(key=lambda r: r.order)
    cited = list(dict.fromkeys(r.source_id for r in reading))
    return Brief(
        topic=title,
        summary=str(obj.get("summary", "")).strip(),
        reading_list=reading,
        prerequisites=_as_str_list(obj.get("prerequisites")),
        learning_path=_as_str_list(obj.get("learning_path")),
        sources=sources,
        cited=cited,
        degraded=False,
    )


def _plan_prompt(topics: list[tuple[str, str]]) -> str:
    lines = ["Topics to order (topic :: summary):"]
    for name, summary in topics:
        lines.append(f"- {name} :: {summary or '(no summary)'}")
    lines.append(
        "\nReturn JSON with keys: "
        '"study_path" (array of {"topic","rationale","prereqs"[]}, in learning order), '
        '"flags" (array of strings for gaps or caveats). '
        "Use only the topic names given above."
    )
    return "\n".join(lines)


def synthesize_plan(engine: Engine, topics: list[tuple[str, str]]) -> StudyPlan:
    reply = engine.run(
        EngineRequest(
            system=_PLAN_SYSTEM,
            prompt=_plan_prompt(topics),
            context={"topic_count": len(topics)},
        )
    )
    obj = _parse_json_object(reply.text)
    valid = {name for name, _ in topics}
    if obj is None:
        steps = [StudyStep(topic=name, rationale="", prereqs=[]) for name, _ in topics]
        return StudyPlan(steps=steps, flags=[], degraded=True)

    steps: list[StudyStep] = []
    for item in obj.get("study_path") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("topic", "")).strip()
        if name not in valid:  # drop any topic the model invented
            continue
        prereqs = [p for p in _as_str_list(item.get("prereqs")) if p in valid]
        steps.append(StudyStep(topic=name, rationale=str(item.get("rationale", "")).strip(),
                               prereqs=prereqs))
    if not steps:  # model returned nothing usable -> fall back to given order
        steps = [StudyStep(topic=name, rationale="", prereqs=[]) for name, _ in topics]
        return StudyPlan(steps=steps, flags=_as_str_list(obj.get("flags")), degraded=True)
    return StudyPlan(steps=steps, flags=_as_str_list(obj.get("flags")), degraded=False)


def _source_map(sources: list[Source]) -> dict[str, Source]:
    return {s.source_id: s for s in sources}


def render_brief(brief: Brief) -> str:
    smap = _source_map(brief.sources)
    out = [f"# Research brief: {brief.topic}", ""]
    if brief.degraded:
        out += ["> No synthesis engine configured — raw discovered sources below.", ""]
    if brief.summary:
        out += ["## Summary", brief.summary, ""]
    if brief.prerequisites:
        out += ["## Prerequisites", *[f"- {p}" for p in brief.prerequisites], ""]
    if brief.learning_path:
        steps = [f"{i}. {s}" for i, s in enumerate(brief.learning_path, 1)]
        out += ["## Learning path", *steps, ""]
    out += ["## Reading list"]
    for item in brief.reading_list:
        src = smap.get(item.source_id)
        title = src.title if src else item.source_id
        url = f" — <{src.url}>" if src and src.url else ""
        out.append(f"{item.order}. **{title}**{url}")
        if item.why:
            out.append(f"   {item.why}")
    out += ["", "## Sources"]
    for src in brief.sources:
        authors = f" · {', '.join(src.authors[:3])}" if src.authors else ""
        year = f" ({src.year})" if src.year else ""
        out.append(f"- `{src.source_id}` [{src.title}]({src.url}){year}{authors}")
    return "\n".join(out).rstrip() + "\n"


def render_plan(plan: StudyPlan) -> str:
    out = ["# Study plan", ""]
    if plan.degraded:
        out += ["> No synthesis engine configured — topics in discovery order.", ""]
    for i, step in enumerate(plan.steps, start=1):
        out.append(f"{i}. **{step.topic}**")
        if step.prereqs:
            out.append(f"   _prereqs:_ {', '.join(step.prereqs)}")
        if step.rationale:
            out.append(f"   {step.rationale}")
    if plan.flags:
        out += ["", "## Flags", *[f"- {f}" for f in plan.flags]]
    return "\n".join(out).rstrip() + "\n"
