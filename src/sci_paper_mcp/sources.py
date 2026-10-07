"""Thin clients for arXiv and Semantic Scholar."""

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field

import httpx

from . import config

ARXIV_API = "https://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1"
ATOM = {"a": "http://www.w3.org/2005/Atom"}
S2_FIELDS = (
    "title,abstract,year,authors,venue,externalIds,citationCount,"
    "openAccessPdf,publicationTypes"
)
_ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?$|[a-z\-]+(\.[A-Z]{2})?/\d{7}(v\d+)?$")


@dataclass
class Paper:
    title: str
    authors: list[str]
    year: int | None = None
    abstract: str | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    s2_id: str | None = None
    citations: int | None = None
    pdf_url: str | None = None
    source: str = ""
    publication_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _client() -> httpx.Client:
    headers = {"User-Agent": "sci-paper-mcp/0.1"}
    if key := config.s2_api_key():
        headers["x-api-key"] = key
    return httpx.Client(headers=headers, timeout=30, follow_redirects=True)


def search_arxiv(query: str, limit: int) -> list[Paper]:
    with _client() as c:
        r = c.get(ARXIV_API, params={"search_query": f"all:{query}", "max_results": limit})
        r.raise_for_status()
    papers = []
    for e in ET.fromstring(r.text).findall("a:entry", ATOM):
        raw_id = e.findtext("a:id", "", ATOM).rsplit("/abs/", 1)[-1]
        arxiv_id = re.sub(r"v\d+$", "", raw_id)
        published = e.findtext("a:published", "", ATOM)
        doi = e.find("{http://arxiv.org/schemas/atom}doi")
        papers.append(
            Paper(
                title=" ".join(e.findtext("a:title", "", ATOM).split()),
                authors=[a.findtext("a:name", "", ATOM) for a in e.findall("a:author", ATOM)],
                year=int(published[:4]) if published else None,
                abstract=" ".join(e.findtext("a:summary", "", ATOM).split()) or None,
                doi=doi.text if doi is not None else None,
                arxiv_id=arxiv_id,
                pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
                source="arxiv",
            )
        )
    return papers


def _from_s2(d: dict) -> Paper:
    ids = d.get("externalIds") or {}
    return Paper(
        title=d.get("title") or "",
        authors=[a.get("name", "") for a in d.get("authors") or []],
        year=d.get("year"),
        abstract=d.get("abstract"),
        venue=d.get("venue") or None,
        doi=ids.get("DOI"),
        arxiv_id=ids.get("ArXiv"),
        s2_id=d.get("paperId"),
        citations=d.get("citationCount"),
        pdf_url=(d.get("openAccessPdf") or {}).get("url") or None,
        source="semantic_scholar",
        publication_types=d.get("publicationTypes") or [],
    )


def search_semantic_scholar(query: str, limit: int) -> list[Paper]:
    with _client() as c:
        r = c.get(
            f"{S2_API}/paper/search",
            params={"query": query, "limit": limit, "fields": S2_FIELDS},
        )
        r.raise_for_status()
    return [_from_s2(d) for d in r.json().get("data", [])]


def s2_identifier(identifier: str) -> str:
    """Map a DOI / arXiv id / S2 id onto the Semantic Scholar path form."""
    ident = identifier.strip()
    ident = re.sub(r"^https?://(dx\.)?doi\.org/", "", ident)
    ident = re.sub(r"^https?://arxiv\.org/(abs|pdf)/", "", ident).removesuffix(".pdf")
    if ident.lower().startswith("arxiv:"):
        ident = ident[6:]
    if ident.startswith("10."):
        return f"DOI:{ident}"
    if _ARXIV_ID.match(ident):
        return f"ARXIV:{re.sub(r'v\d+$', '', ident)}"
    return ident


def get_s2_paper(identifier: str, extra_fields: str = "") -> dict:
    fields = S2_FIELDS + (f",{extra_fields}" if extra_fields else "")
    with _client() as c:
        r = c.get(
            f"{S2_API}/paper/{s2_identifier(identifier)}", params={"fields": fields}
        )
        r.raise_for_status()
    return r.json()
