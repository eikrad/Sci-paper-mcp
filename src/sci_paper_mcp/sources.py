"""arXiv, Semantic Scholar and OpenAlex adapters: each turns its API's JSON into the shared Paper."""

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from typing import Literal, Self

import httpx

from . import config

ARXIV_API = "https://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1"
OPENALEX_API = "https://api.openalex.org"
ATOM = {"a": "http://www.w3.org/2005/Atom"}
S2_FIELDS = "title,abstract,year,authors,venue,externalIds,citationCount,openAccessPdf,publicationTypes"
S2_PAPER_FIELDS = f"{S2_FIELDS},influentialCitationCount,authors.hIndex"
_ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?$|[a-z\-]+(\.[A-Z]{2})?/\d{7}(v\d+)?$")


@dataclass
class Paper:
    """One paper as one or several sources know it. Unknown fields are None (or empty)."""

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
    # trust signals; retracted None means unknown, citations_openalex is never used for the verdict
    source_type: str | None = None
    retracted: bool | None = None
    in_doaj: bool | None = None
    influential_citations: int | None = None
    max_author_h_index: int | None = None
    citations_openalex: int | None = None
    openalex_id: str | None = None

    @property
    def semantic_scholar_url(self) -> str | None:
        return f"https://www.semanticscholar.org/paper/{self.s2_id}" if self.s2_id else None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Identifier:
    """A DOI, arXiv id (no version) or Semantic Scholar id; each adapter maps it to its own path."""

    kind: Literal["doi", "arxiv", "s2"]
    value: str

    @classmethod
    def parse(cls, raw: str) -> Self:
        ident = re.sub(r"^https?://(dx\.)?doi\.org/", "", raw.strip())
        ident = re.sub(r"^https?://arxiv\.org/(abs|pdf)/", "", ident).removesuffix(".pdf")
        if ident.lower().startswith("arxiv:"):
            ident = ident[6:]
        if ident.startswith("10."):
            return cls("doi", ident)
        if _ARXIV_ID.match(ident):
            return cls("arxiv", re.sub(r"v\d+$", "", ident))
        return cls("s2", ident)


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": "sci-paper-mcp/0.1"}, timeout=30, follow_redirects=True)


def _s2_headers() -> dict:
    key = config.s2_api_key()
    return {"x-api-key": key} if key else {}


def _openalex_headers() -> dict:
    key = config.openalex_api_key()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _get(
    c: httpx.Client, url: str, params: dict, headers: dict, key_hint: str, tries: int = 4
) -> httpx.Response:
    """GET with backoff on 429; both scholarly APIs throttle anonymous clients."""
    for attempt in range(tries):
        r = c.get(url, params=params, headers=headers)
        if r.status_code != 429 or attempt == tries - 1:
            break
        retry_after = r.headers.get("Retry-After", "")
        time.sleep(min(float(retry_after) if retry_after.isdigit() else 2**attempt, 10))
    if r.status_code == 429:
        hint = "" if headers else f" Set {key_hint} for a higher rate limit."
        raise httpx.HTTPStatusError(f"rate limited by {url}.{hint}", request=r.request, response=r)
    r.raise_for_status()
    return r


def _arxiv_query(query: str) -> str:
    """AND every term (or "quoted phrase"); a bare `all:a b c` only binds the field to `a`."""
    terms = re.findall(r'"[^"]+"|\S+', query)
    return " AND ".join(f"all:{t}" for t in terms)


def search_arxiv(query: str, limit: int) -> list[Paper]:
    with _client() as c:
        r = c.get(ARXIV_API, params={"search_query": _arxiv_query(query), "max_results": limit})
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
    authors = d.get("authors") or []
    h_indexes = [a["hIndex"] for a in authors if a.get("hIndex") is not None]
    return Paper(
        title=d.get("title") or "",
        authors=[a.get("name", "") for a in authors],
        year=d.get("year"),
        abstract=d.get("abstract"),
        venue=(d.get("venue") or "").strip() or None,
        doi=ids.get("DOI"),
        arxiv_id=ids.get("ArXiv"),
        s2_id=d.get("paperId"),
        citations=d.get("citationCount"),
        pdf_url=(d.get("openAccessPdf") or {}).get("url") or None,
        source="semantic_scholar",
        publication_types=d.get("publicationTypes") or [],
        influential_citations=d.get("influentialCitationCount"),
        max_author_h_index=max(h_indexes, default=None),
    )


def search_semantic_scholar(query: str, limit: int) -> list[Paper]:
    with _client() as c:
        r = _get(
            c,
            f"{S2_API}/paper/search",
            {"query": query, "limit": limit, "fields": S2_FIELDS},
            _s2_headers(),
            "S2_API_KEY",
        )
    return [_from_s2(d) for d in r.json().get("data", [])]


def get_s2_paper(ident: Identifier) -> Paper:
    """Raises httpx.HTTPError; a 404 is an HTTPStatusError."""
    path = {"doi": f"DOI:{ident.value}", "arxiv": f"ARXIV:{ident.value}", "s2": ident.value}[ident.kind]
    with _client() as c:
        r = _get(c, f"{S2_API}/paper/{path}", {"fields": S2_PAPER_FIELDS}, _s2_headers(), "S2_API_KEY")
    return _from_s2(r.json())


OPENALEX_FIELDS = (
    "id,doi,display_name,publication_year,is_retracted,authorships,primary_location,"
    "best_oa_location,cited_by_count,abstract_inverted_index"
)
_ARXIV_DATACITE = re.compile(r"^10\.48550/arxiv\.(.+)$", re.I)


def openalex_work_id(ident: Identifier, s2_doi: str | None = None) -> str | None:
    """OpenAlex path for a DOI or arXiv id (via its DataCite DOI); a bare S2 id needs the DOI S2 gave."""
    match ident.kind:
        case "doi":
            return f"https://doi.org/{ident.value}"
        case "arxiv":
            return f"https://doi.org/10.48550/arXiv.{ident.value}"
        case _:
            return f"https://doi.org/{s2_doi}" if s2_doi else None


def _abstract_from_index(index: dict | None) -> str | None:
    """OpenAlex ships abstracts as {word: [positions]}; put the words back in order."""
    if not index:
        return None
    by_position = {pos: word for word, positions in index.items() for pos in positions}
    return " ".join(by_position[i] for i in sorted(by_position)) or None


def _from_openalex(w: dict) -> Paper:
    doi = re.sub(r"^https?://doi\.org/", "", w.get("doi") or "").lower() or None
    arxiv_id = None
    if doi and (m := _ARXIV_DATACITE.match(doi)):
        arxiv_id, doi = m[1], None
    primary = w.get("primary_location") or {}
    source = primary.get("source") or {}
    is_repository = source.get("type") == "repository"
    return Paper(
        title=w.get("display_name") or "",
        authors=[(a.get("author") or {}).get("display_name", "") for a in w.get("authorships") or []],
        year=w.get("publication_year"),
        abstract=_abstract_from_index(w.get("abstract_inverted_index")),
        venue=None if is_repository else source.get("display_name"),
        doi=doi,
        arxiv_id=arxiv_id,
        # preprint counts are split across versions, so they would understate the paper
        citations=None if is_repository else w.get("cited_by_count"),
        pdf_url=primary.get("pdf_url") or (w.get("best_oa_location") or {}).get("pdf_url"),
        source="openalex",
        source_type=source.get("type"),  # journal | conference | repository | ...
        retracted=bool(w.get("is_retracted")),
        in_doaj=source.get("is_in_doaj"),
        citations_openalex=w.get("cited_by_count"),
        openalex_id=w.get("id"),
    )


def get_openalex_work(work_id: str) -> Paper:
    """Raises httpx.HTTPError; a 404 is an HTTPStatusError."""
    with _client() as c:
        r = _get(
            c,
            f"{OPENALEX_API}/works/{work_id}",
            {"select": OPENALEX_FIELDS},
            _openalex_headers(),
            "OPENALEX_API_KEY",
        )
    return _from_openalex(r.json())


def search_openalex(query: str, limit: int) -> list[Paper]:
    with _client() as c:
        r = _get(
            c,
            f"{OPENALEX_API}/works",
            {"search": query, "per_page": limit, "select": OPENALEX_FIELDS},
            _openalex_headers(),
            "OPENALEX_API_KEY",
        )
    return [_from_openalex(w) for w in r.json().get("results", [])]
