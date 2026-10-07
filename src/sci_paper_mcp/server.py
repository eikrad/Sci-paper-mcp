"""Thin MCP wrapper (stdio) over core."""

from fastmcp import FastMCP

from . import config, core
from .ingest import prepare_ingest as _prepare_ingest

mcp = FastMCP("sci-paper-mcp")


@mcp.tool
def search_papers(query: str, limit: int = 10) -> list[dict]:
    """Search arXiv and Semantic Scholar; results are merged and de-duplicated."""
    return core.search_papers(query, limit)


@mcp.tool
def trust_check(identifier: str) -> dict:
    """Propose a HIGH/MEDIUM/LOW verdict with reasons for a DOI, arXiv id or S2 id. The agent may override it."""
    return core.trust_check(identifier)


@mcp.tool
def fetch_pdf(identifier: str, paper_id: str | None = None, dest_dir: str | None = None) -> dict:
    """Download the open-access PDF (arXiv, Semantic Scholar, Unpaywall) to assets/papers/<PAPER-ID>-<id>.pdf; never overwrites. paper_id like 'RAG-Lewis2020' is derived from author+year if omitted."""
    return core.fetch_pdf(identifier, paper_id, dest_dir)


@mcp.tool
def prepare_ingest(
    paper_id: str, title: str, authors: list[str], topic: str, verdict: str,
    verdict_reasoning: str, abstract: str, key_points: list[str], relevance: str,
    related_pages: list[str], arxiv_id: str | None = None, doi: str | None = None,
    venue: str | None = None, year: int | None = None, citations: int | None = None,
    peer_reviewed: bool = False, semantic_scholar_url: str | None = None,
    pdf_path: str | None = None, language: str = "en", code_url: str | None = None,
) -> dict:
    """Validate against the brain's AGENTS.md and render the paper page. Writes nothing: returns ordered `calls` (create_page, back-link update_page, Log update_page) for the agent to apply via mcp-logseq. pdf_path is the `pdf_path_property` from fetch_pdf."""
    return _prepare_ingest(
        config.second_brain_path(), paper_id=paper_id, title=title, authors=authors, topic=topic,
        verdict=verdict, verdict_reasoning=verdict_reasoning, abstract=abstract,
        key_points=key_points, relevance=relevance, related_pages=related_pages, arxiv_id=arxiv_id,
        doi=doi, venue=venue, year=year, citations=citations, peer_reviewed=peer_reviewed,
        semantic_scholar_url=semantic_scholar_url, pdf_path=pdf_path, language=language,
        code_url=code_url,
    )
