"""Thin MCP wrapper (stdio) over core."""

from fastmcp import FastMCP

from . import config, core
from .ingest import prepare_ingest as _prepare_ingest
from .lint import lint as _lint

mcp = FastMCP("sci-paper-mcp")


@mcp.tool
def search_papers(query: str, limit: int = 10) -> dict:
    """Search arXiv, Semantic Scholar and OpenAlex; results are merged and de-duplicated.

    `warnings` lists sources that failed.
    """
    return core.search_papers(query, limit)


@mcp.tool
def trust_check(identifier: str) -> dict:
    """Propose a HIGH/MEDIUM/LOW verdict with reasons for a DOI, arXiv id or S2 id.

    Combines Semantic Scholar and OpenAlex (retraction flag). The agent may override the verdict.
    """
    return core.trust_check(identifier)


@mcp.tool
def fetch_pdf(identifier: str, paper_id: str | None = None, dest_dir: str | None = None) -> dict:
    """Download the open-access PDF (arXiv, Semantic Scholar, OpenAlex, Unpaywall).

    Saves to assets/papers/<PAPER-ID>-<id>.pdf and never overwrites. paper_id such as
    'RAG-Lewis2020' is derived from first author and year if omitted. The paper is looked up in
    Semantic Scholar and OpenAlex, so either may be down.
    """
    return core.fetch_pdf(config.second_brain_path(), identifier, paper_id, dest_dir)


@mcp.tool
def prepare_ingest(
    identifier: str,
    topic: str,
    verdict: str,
    verdict_reasoning: str,
    key_points: list[str],
    relevance: str,
    related_pages: list[str],
    paper_id: str | None = None,
    language: str = "en",
    code_url: str | None = None,
    abstract: str | None = None,
) -> dict:
    """Validate against the brain's AGENTS.md and render the paper page. Writes nothing.

    You supply the judgement (topic, verdict, key points, relevance, related pages). The server looks
    the paper up by `identifier` (DOI, arXiv id or S2 id) for title, authors, venue, year, citations
    and ids, and finds the PDF in assets/papers/ itself, so run fetch_pdf first (with the same
    paper_id, if you gave one). paper_id defaults to `<FirstAuthor><Year>`, as in fetch_pdf. `abstract`
    only overrides the looked-up one. `warnings` lists failed sources, a missing abstract and missing
    related pages.

    Returns ordered `calls` to apply with mcp-logseq: create_page, one back-link update_page per
    existing related page, then the Log update_page.

    Refuses if Logseq has a different graph open than SECOND_BRAIN_PATH, or none (needs
    LOGSEQ_API_TOKEN to check; without it this only warns).
    """
    return _prepare_ingest(
        config.second_brain_path(),
        identifier=identifier,
        topic=topic,
        verdict=verdict,
        verdict_reasoning=verdict_reasoning,
        key_points=key_points,
        relevance=relevance,
        related_pages=related_pages,
        paper_id=paper_id,
        language=language,
        code_url=code_url,
        abstract=abstract,
    )


@mcp.tool
def lint() -> dict:
    """Read-only health check of the brain at SECOND_BRAIN_PATH. Changes nothing.

    Checks schema conformance, PDF paths, backlinks, Related Pages links, empty highlights,
    stale pages and AGENTS.md/Templates drift. Judgement calls (contradictions, concept gaps)
    are left to the agent.
    """
    return _lint(config.second_brain_path())
