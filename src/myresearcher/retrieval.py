from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from xml.etree import ElementTree as ET

# The one network boundary. Default shells out to urllib; tests inject a fake so
# the HTTP call is the only thing mocked (same discipline as engine/github Runners).
Fetcher = Callable[..., bytes]

ARXIV_ENDPOINT = "http://export.arxiv.org/api/query"
TAVILY_ENDPOINT = "https://api.tavily.com/search"

_ATOM = {"a": "http://www.w3.org/2005/Atom"}

# A short, deterministic stopword set — enough to keep query terms meaningful
# without pulling an NLP dependency (harness: dependency-free runtime).
_STOPWORDS = frozenset(
    "a an and are as at be by for from how in into is it of on or the to via with "
    "what why study learn learning research overview intro introduction".split()
)


@dataclass(frozen=True)
class Source:
    source_id: str  # "arxiv:2401.00001" | "web:1"
    title: str
    url: str
    snippet: str
    origin: str  # "arxiv" | "web"
    authors: list[str] = field(default_factory=list)
    year: int | None = None


def _http(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https/http endpoints
        return resp.read()


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    word = []
    for ch in text.lower():
        if ch.isalnum():
            word.append(ch)
        elif word:
            out.append("".join(word))
            word = []
    if word:
        out.append("".join(word))
    return out


def build_query(title: str, body: str) -> str:
    # Title terms first (higher signal), then body terms, deduped in order,
    # stopwords and 1-char tokens dropped. Deterministic — same input, same query.
    seen: set[str] = set()
    terms: list[str] = []
    for tok in tokenize(title) + tokenize(body):
        if tok in _STOPWORDS or len(tok) < 2 or tok in seen:
            continue
        seen.add(tok)
        terms.append(tok)
    return " ".join(terms[:12])


def _year_of(published: str | None) -> int | None:
    if not published or len(published) < 4 or not published[:4].isdigit():
        return None
    return int(published[:4])


def search_arxiv(query: str, *, fetch: Fetcher = _http, limit: int = 10) -> list[Source]:
    if not query:
        return []
    params = urllib.parse.urlencode(
        {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )
    raw = fetch(f"{ARXIV_ENDPOINT}?{params}")
    root = ET.fromstring(raw)
    sources: list[Source] = []
    for entry in root.findall("a:entry", _ATOM):
        eid = (entry.findtext("a:id", default="", namespaces=_ATOM) or "").strip()
        arxiv_id = eid.rsplit("/abs/", 1)[-1] if "/abs/" in eid else eid.rsplit("/", 1)[-1]
        title = " ".join((entry.findtext("a:title", "", _ATOM) or "").split())
        summary = " ".join((entry.findtext("a:summary", "", _ATOM) or "").split())
        authors = [
            (a.findtext("a:name", "", _ATOM) or "").strip()
            for a in entry.findall("a:author", _ATOM)
        ]
        sources.append(
            Source(
                source_id=f"arxiv:{arxiv_id}",
                title=title,
                url=eid,
                snippet=summary,
                origin="arxiv",
                authors=[a for a in authors if a],
                year=_year_of(entry.findtext("a:published", None, _ATOM)),
            )
        )
    return sources


def search_web(
    query: str,
    *,
    api_key: str | None,
    fetch: Fetcher = _http,
    limit: int = 10,
) -> list[Source]:
    # Tavily: a single JSON POST returning ranked, snippet-bearing results built
    # for LLM consumption. No key configured → no web results (arXiv still works).
    if not query or not api_key:
        return []
    body = json.dumps(
        {"api_key": api_key, "query": query, "max_results": limit, "search_depth": "basic"}
    ).encode()
    raw = fetch(TAVILY_ENDPOINT, data=body, headers={"Content-Type": "application/json"})
    payload = json.loads(raw)
    sources: list[Source] = []
    for i, item in enumerate(payload.get("results", []), start=1):
        sources.append(
            Source(
                source_id=f"web:{i}",
                title=(item.get("title") or item.get("url") or "").strip(),
                url=(item.get("url") or "").strip(),
                snippet=" ".join((item.get("content") or "").split()),
                origin="web",
            )
        )
    return sources


def _score(source: Source, query_tokens: set[str], this_year: int) -> tuple[int, int, str]:
    haystack = set(tokenize(source.title)) | set(tokenize(source.snippet))
    overlap = len(query_tokens & haystack)
    recency = source.year if source.year is not None else 0
    # Higher overlap, then more recent, then id for a stable deterministic order.
    return (overlap, min(recency, this_year), source.source_id)


def retrieve(
    title: str,
    body: str,
    *,
    sources: tuple[str, ...] = ("arxiv", "web"),
    top: int = 15,
    fetch: Fetcher = _http,
    api_key: str | None = None,
) -> list[Source]:
    query = build_query(title, body)
    found: list[Source] = []
    if "arxiv" in sources:
        found += search_arxiv(query, fetch=fetch, limit=top)
    if "web" in sources:
        found += search_web(query, api_key=api_key, fetch=fetch, limit=top)

    deduped: dict[str, Source] = {}
    for src in found:
        key = src.url.rstrip("/").lower() or src.source_id
        deduped.setdefault(key, src)

    query_tokens = set(tokenize(query))
    this_year = datetime.now(UTC).year
    ranked = sorted(
        deduped.values(),
        key=lambda s: _score(s, query_tokens, this_year),
        reverse=True,
    )
    return ranked[:top]
