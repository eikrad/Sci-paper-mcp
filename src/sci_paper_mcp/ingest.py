"""prepare_ingest: validate and render a paper page; the agent applies it via mcp-logseq (ADR 0002)."""

from datetime import date
from pathlib import Path

from .schema import Schema, SchemaError, load_schema, page_exists

VERDICTS = ("HIGH", "MEDIUM", "LOW")


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items)


def prepare_ingest(
    root: Path | None,
    *,
    paper_id: str,
    title: str,
    authors: list[str],
    topic: str,
    verdict: str,
    verdict_reasoning: str,
    abstract: str,
    key_points: list[str],
    relevance: str,
    related_pages: list[str],
    arxiv_id: str | None = None,
    doi: str | None = None,
    venue: str | None = None,
    year: int | None = None,
    citations: int | None = None,
    peer_reviewed: bool = False,
    semantic_scholar_url: str | None = None,
    pdf_path: str | None = None,
    language: str = "en",
    code_url: str | None = None,
    today: date | None = None,
) -> dict:
    schema: Schema = load_schema(root)
    errors = []
    if topic not in schema.taxonomy:
        errors.append(f"topic '{topic}' not in taxonomy {schema.taxonomy}")
    if language not in schema.values["language"]:
        errors.append(f"language '{language}' not in {schema.values['language']}")
    if verdict not in VERDICTS:
        errors.append(f"verdict must be one of {VERDICTS}")
    if not (arxiv_id or doi):
        errors.append("need arxiv_id or doi for document-id")
    page_title = f"Sources/Research/{paper_id}"
    if page_exists(schema.root, page_title):
        errors.append(f"page '{page_title}' already exists")
    if errors:
        raise SchemaError("; ".join(errors))

    warnings = []
    if not 3 <= len(related_pages) <= 5:
        warnings.append(f"AGENTS.md asks for 3-5 related pages, got {len(related_pages)}")
    missing = [p for p in related_pages if not page_exists(schema.root, p)]
    if missing:
        warnings.append(f"related pages do not exist: {missing}")
    related_ok = [p for p in related_pages if p not in missing]

    stem = Path(pdf_path).stem if pdf_path and pdf_path != "not-found" else f"{paper_id}-{arxiv_id or 'na'}"
    document_id = f"arXiv:{arxiv_id}" if arxiv_id else f"doi:{doi}"
    today = today or date.today()

    body = {
        "Abstract": abstract,
        "Key Points": _bullets(key_points),
        "Relevance to This Project": relevance,
        "Related Pages": _bullets([f"[[{p}]]" for p in related_pages]),
        "Verification": _bullets([
            f"**Verdict:** {verdict} — {verdict_reasoning}",
            f"**Citations:** {citations if citations is not None else 'unknown'}",
            f"**Venue:** {venue or 'none (preprint)'}",
            f"**Peer-reviewed:** {'Yes' if peer_reviewed else 'No'}",
            f"**Semantic Scholar:** {semantic_scholar_url or 'not found'}",
            f"**PDF:** {'Present — ' + pdf_path if pdf_path and pdf_path != 'not-found' else 'not found'}",
        ]),
        "Highlights": f"- {{{{embed [[hls__{stem}]]}}}}",
        "Local PDF": f"- [{stem}.pdf]({pdf_path})" if pdf_path and pdf_path != "not-found" else "- not found",
    }
    parts = [f"# {title}", f"**Authors:** {', '.join(authors)}"]
    parts.append(f"**Venue:** {venue or 'n/a'}" + (f" ({year})" if year else ""))
    if code_url:
        parts.append(f"**Code:** {code_url}")
    for heading in schema.sections:
        if heading not in body:
            warnings.append(f"template section '{heading}' is unknown to the server; left empty")
        parts.append(f"## {heading}\n{body.get(heading, '')}")

    properties = {
        "source-type": "paper",
        "document-id": document_id,
        "topic": topic,
        "language": language,
        "status": "ingested",
        "date": today.isoformat(),
        "url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else f"https://doi.org/{doi}",
        "trustworthiness": verdict,
        "pdf-path": pdf_path or "not-found",
    }
    calls = [{"tool": "create_page", "arguments": {
        "title": page_title, "properties": properties, "content": "\n\n".join(parts)}}]
    calls += [
        {"tool": "update_page", "arguments": {
            "page_name": p, "mode": "append", "content": f"- See also [[{page_title}]] — {title}"}}
        for p in related_ok
    ]
    calls.append({"tool": "update_page", "arguments": {
        "page_name": "Log", "mode": "append",
        "content": (f"## [{today.isoformat()}] ingest | {page_title}\n"
                    f"- New page ({verdict}); back-links added to {len(related_ok)} related page(s); "
                    "highlights not yet extracted")}})
    return {"page": page_title, "calls": calls, "warnings": warnings,
            "next": "Apply `calls` in order with mcp-logseq, then annotate the PDF in Logseq."}
