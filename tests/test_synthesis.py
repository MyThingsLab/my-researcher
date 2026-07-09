from __future__ import annotations

import json

from mythings.engine import NoopEngine

from conftest import ScriptedEngine
from myresearcher.retrieval import Source
from myresearcher.synthesis import (
    render_brief,
    render_plan,
    synthesize_brief,
    synthesize_plan,
)

_SOURCES = [
    Source("arxiv:1", "GNN paper", "http://arxiv.org/abs/1", "graph nets", "arxiv", year=2021),
    Source("arxiv:2", "MPNN survey", "http://arxiv.org/abs/2", "message passing", "arxiv"),
]


def test_synthesize_brief_parses_engine_json() -> None:
    reply = json.dumps(
        {
            "summary": "GNNs learn on graphs.",
            "reading_list": [{"source_id": "arxiv:2", "why": "start here", "order": 1}],
            "prerequisites": ["linear algebra"],
            "learning_path": ["basics", "message passing"],
        }
    )
    brief = synthesize_brief(ScriptedEngine(reply), "GNN", "", _SOURCES)
    assert not brief.degraded
    assert brief.summary == "GNNs learn on graphs."
    assert brief.cited == ["arxiv:2"]
    assert brief.prerequisites == ["linear algebra"]


def test_synthesize_brief_drops_invented_source() -> None:
    reply = json.dumps(
        {
            "summary": "x",
            "reading_list": [
                {"source_id": "arxiv:1", "why": "real", "order": 1},
                {"source_id": "arxiv:999", "why": "hallucinated", "order": 2},
            ],
        }
    )
    brief = synthesize_brief(ScriptedEngine(reply), "GNN", "", _SOURCES)
    assert brief.cited == ["arxiv:1"]  # the invented id is dropped


def test_synthesize_brief_tolerates_preamble_before_json() -> None:
    reply = (
        "Sure, here is the brief:\n\n"
        + json.dumps({"summary": "GNNs learn on graphs.", "reading_list": []})
        + "\nLet me know if you need anything else."
    )
    brief = synthesize_brief(ScriptedEngine(reply), "GNN", "", _SOURCES)
    assert not brief.degraded
    assert brief.summary == "GNNs learn on graphs."


def test_synthesize_brief_matches_source_id_without_version_suffix() -> None:
    url = "http://arxiv.org/abs/2304.02660v4"
    sources = [Source("arxiv:2304.02660v4", "Generalized Charges", url, "s", "arxiv")]
    reply = json.dumps(
        {
            "summary": "x",
            # model cites the bare id, dropping the version -- a common habit
            "reading_list": [{"source_id": "arxiv:2304.02660", "why": "start here", "order": 1}],
        }
    )
    brief = synthesize_brief(ScriptedEngine(reply), "Symmetries", "", sources)
    assert brief.cited == ["arxiv:2304.02660v4"]  # matched to the real source, not dropped


def test_synthesize_brief_research_level_changes_system_prompt() -> None:
    reply = json.dumps({"summary": "x", "reading_list": []})
    engine = ScriptedEngine(reply)
    synthesize_brief(engine, "GNN", "", _SOURCES, level="research")
    assert "research-level reader" in engine.calls[-1].system

    synthesize_brief(engine, "GNN", "", _SOURCES)  # default level
    assert "research-level reader" not in engine.calls[-1].system


def test_synthesize_brief_degrades_on_noop() -> None:
    brief = synthesize_brief(NoopEngine(), "GNN", "", _SOURCES)
    assert brief.degraded
    assert brief.summary == ""
    assert [i.source_id for i in brief.reading_list] == ["arxiv:1", "arxiv:2"]


def test_render_brief_includes_citations_and_sources() -> None:
    brief = synthesize_brief(NoopEngine(), "GNN", "", _SOURCES)
    md = render_brief(brief)
    assert "# Research brief: GNN" in md
    assert "`arxiv:1`" in md and "`arxiv:2`" in md
    assert "http://arxiv.org/abs/1" in md


def test_synthesize_plan_orders_topics() -> None:
    reply = json.dumps(
        {
            "study_path": [
                {"topic": "RBM", "rationale": "foundational", "prereqs": []},
                {"topic": "GNN", "rationale": "builds on it", "prereqs": ["RBM"]},
            ],
            "flags": ["no reservoir computing source yet"],
        }
    )
    plan = synthesize_plan(ScriptedEngine(reply), [("GNN", "a"), ("RBM", "b")])
    assert not plan.degraded
    assert [s.topic for s in plan.steps] == ["RBM", "GNN"]
    assert plan.steps[1].prereqs == ["RBM"]
    assert plan.flags == ["no reservoir computing source yet"]


def test_synthesize_plan_degrades_to_given_order() -> None:
    plan = synthesize_plan(NoopEngine(), [("GNN", "a"), ("RBM", "b")])
    assert plan.degraded
    assert [s.topic for s in plan.steps] == ["GNN", "RBM"]


def test_render_plan_numbers_steps() -> None:
    plan = synthesize_plan(NoopEngine(), [("GNN", "a"), ("RBM", "b")])
    md = render_plan(plan)
    assert "1. **GNN**" in md and "2. **RBM**" in md
