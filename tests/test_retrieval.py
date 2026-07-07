from __future__ import annotations

from conftest import fake_fetch
from myresearcher.retrieval import build_query, retrieve, search_arxiv, search_web


def test_build_query_drops_stopwords_and_dedupes() -> None:
    q = build_query("Learning Graph Neural Networks", "What are graph neural networks for?")
    terms = q.split()
    assert "graph" in terms and "neural" in terms and "networks" in terms
    assert "learning" not in terms  # stopword
    assert "what" not in terms  # stopword
    assert terms.count("graph") == 1  # deduped across title + body


def test_search_arxiv_parses_atom_entries() -> None:
    sources = search_arxiv("graph neural networks", fetch=fake_fetch)
    assert [s.source_id for s in sources] == ["arxiv:2101.00001v1", "arxiv:1901.00002v2"]
    first = sources[0]
    assert first.origin == "arxiv"
    assert first.year == 2021
    assert first.authors == ["Ada Lovelace"]
    assert "physical systems" in first.snippet


def test_search_web_returns_nothing_without_api_key() -> None:
    assert search_web("graph neural networks", api_key=None, fetch=fake_fetch) == []


def test_search_web_parses_provider_results() -> None:
    sources = search_web("graph neural networks", api_key="k", fetch=fake_fetch)
    assert len(sources) == 1
    assert sources[0].origin == "web"
    assert sources[0].url == "https://distill.pub/2021/gnn-intro/"


def test_retrieve_merges_backends_and_ranks_by_overlap() -> None:
    sources = retrieve(
        "Graph Neural Networks",
        "message passing on graphs",
        fetch=fake_fetch,
        api_key="k",
        top=15,
    )
    ids = {s.source_id for s in sources}
    assert ids == {"arxiv:2101.00001v1", "arxiv:1901.00002v2", "web:1"}
    # The message-passing survey shares the most terms with the body, so it ranks first.
    assert sources[0].source_id == "arxiv:1901.00002v2"


def test_retrieve_caps_at_top() -> None:
    sources = retrieve("Graph Neural Networks", "", fetch=fake_fetch, api_key="k", top=2)
    assert len(sources) == 2
