"""prepare_ingest: look the paper up, validate and render its page; the agent applies it (ADR 0002, 0007)."""

from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx

from . import config, core, untrusted
from .brain import (
    Brain,
    SchemaError,
    highlights_embed,
    paper_properties,
    paper_title,
    pdf_name,
    pdf_stem,
    resolve_paper_id,
)
from .verdict import is_preprint

VERDICTS = ("HIGH", "MEDIUM", "LOW")


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items)


def _verify_open_graph(root: Path) -> str | None:
    """Ask Logseq which graph is open (read-only). Raises on a mismatch, returns a warning if unsure.

    mcp-logseq writes into whatever graph Logseq has open, independent of SECOND_BRAIN_PATH.
    """
    token = config.logseq_api_token()
    if not token:
        return "could not verify the open Logseq graph: LOGSEQ_API_TOKEN is not set"
    try:
        r = httpx.post(
            f"{config.logseq_api_url()}/api",
            headers={"Authorization": f"Bearer {token}"},
            json={"method": "logseq.App.getCurrentGraph", "args": []},
            timeout=10,
        )
        r.raise_for_status()
        graph = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return f"could not verify the open Logseq graph: {e}"
    if not graph or not graph.get("path"):
        raise SchemaError("no graph is open in Logseq; open the brain before applying the calls")
    if Path(graph["path"]).resolve() != root.resolve():
        raise SchemaError(
            f"wrong graph: Logseq has {graph['path']} open but SECOND_BRAIN_PATH is {root}. "
            "Open the right graph in Logseq, or the pages would land in the wrong brain."
        )
    return None


def _taken(brain: Brain, paper_id: str) -> list[str]:
    title = paper_title(paper_id)
    return [f"page '{title}' already exists"] if brain.has_page(title) else []


def prepare_ingest(
    root: Path | None,
    *,
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
    today: date | None = None,
    verify_graph: bool = True,
    lookup: Callable[[str], core.Lookup] = core.lookup,
) -> dict:
    """The agent brings judgement; the metadata (one lookup) and the PDF (the raw layer) are found here."""
    brain = Brain(root)
    schema = brain.schema
    graph_warning = _verify_open_graph(brain.root) if verify_graph else None

    errors = []
    if topic not in schema.taxonomy:
        errors.append(f"topic '{topic}' not in taxonomy {schema.taxonomy}")
    if language not in schema.values["language"]:
        errors.append(f"language '{language}' not in {schema.values['language']}")
    if verdict not in VERDICTS:
        errors.append(f"verdict must be one of {VERDICTS}")
    if paper_id:  # a derived one needs the author and year from the lookup
        paper_id = resolve_paper_id(paper_id, [], None)
        errors += _taken(brain, paper_id)
    if errors:
        raise SchemaError("; ".join(errors))

    found = lookup(identifier)
    if (paper := found.paper) is None:
        raise SchemaError(f"{identifier} not found on Semantic Scholar or OpenAlex")
    if not (paper.arxiv_id or paper.doi):
        errors.append(f"{identifier} has no DOI or arXiv id for document-id")
    if not paper_id:
        paper_id = resolve_paper_id(None, paper.authors, paper.year)
        errors += _taken(brain, paper_id)
    if errors:
        raise SchemaError("; ".join(errors))
    page_title = paper_title(paper_id)

    warnings = ([graph_warning] if graph_warning else []) + found.warnings
    if not 3 <= len(related_pages) <= 5:
        warnings.append(f"AGENTS.md asks for 3-5 related pages, got {len(related_pages)}")
    missing = [p for p in related_pages if not brain.has_page(p)]
    if missing:
        warnings.append(f"related pages do not exist: {missing}")
    related_ok = [p for p in related_pages if p not in missing]

    paper.title, title_flags = untrusted.scrub("title", paper.title)  # both end up in the graph
    abstract, abstract_flags = untrusted.scrub("abstract", abstract or paper.abstract or "")
    warnings += title_flags + abstract_flags
    if not abstract:
        warnings.append("no abstract from the sources or the agent; Abstract section left empty")

    today = today or date.today()
    ids = dict(arxiv_id=paper.arxiv_id, doi=paper.doi, s2_id=paper.s2_id)
    pdf_path = brain.find_pdf(paper_id, **ids)
    pdf = pdf_path or pdf_name(paper_id, **ids)
    pdf_state = f"Present — {pdf_path}" if pdf_path else "not found"

    body = {
        "Abstract": abstract,
        "Key Points": _bullets(key_points),
        "Relevance to This Project": relevance,
        "Related Pages": _bullets([f"[[{p}]]" for p in related_pages]),
        "Verification": _bullets(
            [
                f"**Verdict:** {verdict} — {verdict_reasoning}",
                f"**Citations:** {'unknown' if paper.citations is None else paper.citations}",
                f"**Venue:** {paper.venue or 'none (preprint)'}",
                f"**Peer-reviewed:** {'No' if is_preprint(paper) else 'Yes'}",
                f"**Semantic Scholar:** {paper.semantic_scholar_url or 'not found'}",
                f"**PDF:** {pdf_state}",
            ]
        ),
        "Highlights": f"- {highlights_embed(pdf)}",
        "Local PDF": f"- [{pdf_stem(pdf)}.pdf]({pdf_path})" if pdf_path else "- not found",
    }
    parts = [f"# {paper.title}", f"**Authors:** {', '.join(paper.authors)}"]
    parts.append(f"**Venue:** {paper.venue or 'n/a'}" + (f" ({paper.year})" if paper.year else ""))
    if code_url:
        parts.append(f"**Code:** {code_url}")
    for heading in schema.sections:
        if heading not in body:
            warnings.append(f"template section '{heading}' is unknown to the server; left empty")
        parts.append(f"## {heading}\n{body.get(heading, '')}")

    properties = paper_properties(
        arxiv_id=paper.arxiv_id,
        doi=paper.doi,
        topic=topic,
        language=language,
        verdict=verdict,
        date=today.isoformat(),
        pdf_path=pdf_path,
    )
    calls = [
        {
            "tool": "create_page",
            "arguments": {"title": page_title, "properties": properties, "content": "\n\n".join(parts)},
        }
    ]
    calls += [
        {
            "tool": "update_page",
            "arguments": {
                "page_name": p,
                "mode": "append",
                "content": f"- See also [[{page_title}]] — {paper.title}",
            },
        }
        for p in related_ok
    ]
    calls.append(
        {
            "tool": "update_page",
            "arguments": {
                "page_name": "Log",
                "mode": "append",
                "content": (
                    f"## [{today.isoformat()}] ingest | {page_title}\n"
                    f"- New page ({verdict}); back-links added to {len(related_ok)} related page(s); "
                    "highlights not yet extracted"
                ),
            },
        }
    )
    return {
        "page": page_title,
        "calls": calls,
        "warnings": warnings,
        "next": "Apply `calls` in order with mcp-logseq, then annotate the PDF in Logseq.",
    }
