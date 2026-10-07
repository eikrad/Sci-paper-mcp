"""Thin MCP wrapper (stdio) over core."""

from fastmcp import FastMCP

from . import core

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
