"""The phase-1 tools as plain functions; CLI and MCP both call these."""

from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Literal

import httpx

from . import config, sources
from .sources import Paper
from .verdict import is_preprint, propose_verdict

UNPAYWALL_API = "https://api.unpaywall.org/v2"

_PRIORITY = {"semantic_scholar": 0, "openalex": 1, "arxiv": 2}  # richest metadata first


def _rank(p: Paper) -> int:
    return _PRIORITY.get(p.source, 9)


def _missing(value) -> bool:
    return value is None or value == ""  # an empty list is a source's answer, not a gap


def _merge(papers: list[Paper]) -> Paper:
    """The richest source wins; lower ones fill every field it leaves unknown."""
    winner, *rest = sorted(papers, key=_rank)
    merged = replace(winner)
    for p in rest:
        for f in fields(Paper):
            if _missing(getattr(merged, f.name)):
                setattr(merged, f.name, getattr(p, f.name))
    return merged


def _dedupe(papers: list[Paper]) -> list[Paper]:
    """Group by arXiv id / DOI / title, then merge each group."""
    groups: list[list[Paper]] = []
    index: dict[str, list[Paper]] = {}
    for p in sorted(papers, key=_rank):
        keys = [k for k in (p.arxiv_id, p.doi and p.doi.lower(), p.title.lower().strip()) if k]
        group = next((index[k] for k in keys if k in index), None)
        if group is None:
            groups.append(group := [])
        group.append(p)
        index.update(dict.fromkeys(keys, group))
    return [_merge(g) for g in groups]


def search_papers(
    query: str, limit: int = 10, sources_: tuple[str, ...] = ("arxiv", "semantic_scholar", "openalex")
) -> dict:
    found: list[Paper] = []
    errors = []
    searchers = {
        "arxiv": sources.search_arxiv,
        "semantic_scholar": sources.search_semantic_scholar,
        "openalex": sources.search_openalex,
    }
    for name in sources_:
        try:
            found += searchers[name](query, limit)
        except httpx.HTTPError as e:  # one source down must not kill the search
            errors.append(f"{name}: {e}")
    results = [p.to_dict() for p in _dedupe(found)[:limit]]
    if errors and not results:
        raise RuntimeError("; ".join(errors))
    return {"results": results, "warnings": errors}


Outcome = Literal["found", "not_found", "failed", "skipped"]


@dataclass
class Lookup:
    paper: Paper | None  # None: every queried source answered "not found"
    outcomes: dict[str, Outcome]  # per source; "skipped" means it could not be addressed (no DOI)
    warnings: list[str]  # one line per failed source


def lookup(identifier: str) -> Lookup:
    """One merged Paper for a DOI, arXiv id or S2 id, from Semantic Scholar and OpenAlex.

    A source that fails (network, 5xx, 429) becomes a warning; one that does not know the paper
    (404) is only an outcome. Raises RuntimeError when no source answered and one failed, since
    the failed one may know the paper.
    """
    ident = sources.Identifier.parse(identifier)
    outcomes: dict[str, Outcome] = {}
    warnings: list[str] = []

    def ask(name: str, fetch) -> Paper | None:
        try:
            paper = fetch()
        except httpx.HTTPError as e:
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 404:
                outcomes[name] = "not_found"
            else:
                outcomes[name] = "failed"
                warnings.append(f"{name}: {e}")
            return None
        outcomes[name] = "found"
        return paper

    s2 = ask("semantic_scholar", lambda: sources.get_s2_paper(ident))
    work_id = sources.openalex_work_id(ident, s2.doi if s2 else None)
    oa = None
    if work_id:
        oa = ask("openalex", lambda: sources.get_openalex_work(work_id))
    else:
        outcomes["openalex"] = "skipped"

    answers = [p for p in (s2, oa) if p is not None]
    if not answers:
        if warnings:
            raise RuntimeError("; ".join(warnings))
        return Lookup(None, outcomes, warnings)
    paper = _merge(answers)
    if ident.kind == "doi":
        paper.doi = paper.doi or ident.value
    elif ident.kind == "arxiv":
        paper.arxiv_id = paper.arxiv_id or ident.value
    return Lookup(paper, outcomes, warnings)


_RETRACTION_GAP = {
    "failed": "OpenAlex unavailable",
    "not_found": "not found in OpenAlex",
    "skipped": "no DOI or arXiv id to look it up in OpenAlex",
}


def trust_check(identifier: str) -> dict:
    """Propose a HIGH/MEDIUM/LOW verdict from Semantic Scholar and OpenAlex together.

    Semantic Scholar supplies venue, citations and author h-index; OpenAlex adds the
    retraction flag and the source type. Either may be missing. A proposal, not a ruling.
    """
    found = lookup(identifier)
    p = found.paper
    if p is None:
        return {"verdict": "LOW", "reasons": ["not found on Semantic Scholar or OpenAlex"], "found": False}
    verdict, reasons = propose_verdict(p)
    if p.retracted is None:
        reasons.append(f"retraction status unknown ({_RETRACTION_GAP[found.outcomes['openalex']]})")
    return {
        "verdict": verdict,
        "reasons": reasons,
        "warnings": found.warnings,
        "found": True,
        "title": p.title or None,
        "year": p.year,
        "venue": p.venue,
        "peer_reviewed": not is_preprint(p),
        "retracted": p.retracted,
        "source_type": p.source_type,
        "in_doaj": p.in_doaj,
        "citations": p.citations,
        "citations_openalex": p.citations_openalex,
        "influential_citations": p.influential_citations,
        "max_author_h_index": p.max_author_h_index,
        "semantic_scholar_url": f"https://www.semanticscholar.org/paper/{p.s2_id}" if p.s2_id else None,
        "openalex_id": p.openalex_id,
    }


def _load_paper(identifier: str, paper_id: str | None) -> Paper:
    """Metadata for naming and PDF lookup; skips the lookup when the arXiv id suffices."""
    ident = sources.Identifier.parse(identifier)
    if ident.kind == "arxiv" and paper_id:
        return Paper(title="", authors=[], arxiv_id=ident.value)
    if (paper := lookup(identifier).paper) is None:
        raise RuntimeError(f"{identifier} not found on Semantic Scholar or OpenAlex")
    return paper


def _pdf_url(p: Paper) -> str:
    if p.arxiv_id:
        return f"https://arxiv.org/pdf/{p.arxiv_id}"
    if p.pdf_url:
        return p.pdf_url
    if p.doi:
        email = config.unpaywall_email()
        if not email:
            raise RuntimeError("No open PDF found; set UNPAYWALL_EMAIL to try Unpaywall.")
        with httpx.Client(timeout=30) as c:
            r = c.get(f"{UNPAYWALL_API}/{p.doi}", params={"email": email})
            r.raise_for_status()
        if url := (r.json().get("best_oa_location") or {}).get("url_for_pdf"):
            return url
    raise RuntimeError(f"No open-access PDF found for {p.title or p.doi or p.arxiv_id}")


def _safe(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in text)


def _default_paper_id(p: Paper) -> str:
    if not p.authors or not p.year:
        raise RuntimeError("Cannot derive a PAPER-ID (author/year unknown); pass paper_id.")
    return f"{_safe(p.authors[0].split()[-1])}{p.year}"


def fetch_pdf(identifier: str, paper_id: str | None = None, dest_dir: str | None = None) -> dict:
    """Download the open-access PDF as `<PAPER-ID>-<id>.pdf`; never overwrites."""
    p = _load_paper(identifier, paper_id)
    url = _pdf_url(p)
    paper_id = _safe(paper_id) if paper_id else _default_paper_id(p)
    id_part = _safe(p.arxiv_id or p.doi or p.s2_id or "unknown")
    name = f"{paper_id}-{id_part}.pdf"

    brain = config.second_brain_path()
    if dest_dir:
        folder = Path(dest_dir).expanduser()
    elif brain:
        folder = brain / "assets" / "papers"
    else:
        folder = config.cache_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    if path.exists():
        raise RuntimeError(f"{path} already exists; the raw layer is never overwritten.")

    with httpx.Client(timeout=60, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise RuntimeError(f"{url} did not return a PDF")
    with path.open("xb") as f:
        f.write(r.content)
    in_brain = brain is not None and not dest_dir
    return {
        "path": str(path),
        "pdf_path_property": f"../assets/papers/{name}" if in_brain else None,
        "paper_id": paper_id,
        "url": url,
        "bytes": len(r.content),
    }
