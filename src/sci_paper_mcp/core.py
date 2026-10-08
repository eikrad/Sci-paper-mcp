"""The phase-1 tools as plain functions; CLI and MCP both call these."""

from copy import deepcopy
from dataclasses import dataclass, fields, replace
from functools import partial
from pathlib import Path
from typing import Literal

import httpx

from . import config, sources
from .brain import Brain, pdf_name, resolve_paper_id, save_pdf
from .sources import Paper
from .verdict import is_preprint, propose_verdict

UNPAYWALL_API = "https://api.unpaywall.org/v2"
MAX_PDF_BYTES = 100 * 2**20  # far above any paper; stops a hostile link from filling memory or disk

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


_memo: dict[sources.Identifier, Lookup] = {}  # complete lookups only, for the life of the process


def lookup(identifier: str) -> Lookup:
    """One merged Paper for a DOI, arXiv id or S2 id, from Semantic Scholar and OpenAlex.

    A source that fails (network, 5xx, 429) becomes a warning; one that does not know the paper
    (404) is only an outcome. Raises RuntimeError when no source answered and one failed, since
    the failed one may know the paper.

    trust_check, fetch_pdf and prepare_ingest look up the same paper in turn, so a lookup that found
    the paper with no source failing is remembered (anonymous Semantic Scholar throttles hard). Failures
    and unknown papers never are; every caller gets its own copy.
    """
    ident = sources.Identifier.parse(identifier)
    if ident in _memo:
        return deepcopy(_memo[ident])
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
    work_ids = sources.openalex_work_ids(ident, s2.doi if s2 else None)
    oa = None
    for work_id in work_ids:  # the next one only when OpenAlex does not know this one
        oa = ask("openalex", partial(sources.get_openalex_work, work_id))
        if outcomes["openalex"] != "not_found":
            break
    if not work_ids:
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
    found = Lookup(paper, outcomes, warnings)
    if not warnings:
        _memo[ident] = deepcopy(found)
    return found


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
        "semantic_scholar_url": p.semantic_scholar_url,
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


def _download_pdf(url: str) -> bytes:
    """The PDF at `url`, read only up to MAX_PDF_BYTES: the link comes from a third party."""
    too_big = RuntimeError(f"{url} is larger than {MAX_PDF_BYTES // 2**20} MB; not saved")
    with httpx.Client(timeout=60, follow_redirects=True) as c, c.stream("GET", url) as r:
        r.raise_for_status()
        if int(r.headers.get("Content-Length") or 0) > MAX_PDF_BYTES:
            raise too_big
        content = bytearray()
        for chunk in r.iter_bytes():
            content += chunk
            if len(content) > MAX_PDF_BYTES:
                raise too_big
    if not content.startswith(b"%PDF"):
        raise RuntimeError(f"{url} did not return a PDF")
    return bytes(content)


def fetch_pdf(
    root: Path | None, identifier: str, paper_id: str | None = None, dest_dir: str | None = None
) -> dict:
    """Download the open-access PDF as `<PAPER-ID>-<id>.pdf`; never overwrites.

    Goes into the Brain's raw layer unless `dest_dir` is given; with no Brain the cache dir.
    """
    p = _load_paper(identifier, paper_id)
    url = _pdf_url(p)
    paper_id = resolve_paper_id(paper_id, p.authors, p.year)
    name = pdf_name(paper_id, arxiv_id=p.arxiv_id, doi=p.doi, s2_id=p.s2_id)
    brain = Brain(root) if root is not None and not dest_dir else None
    if dest_dir:
        folder = Path(dest_dir).expanduser()
    elif brain:
        folder = brain.raw_layer
    else:
        folder = config.cache_dir()

    path = save_pdf(folder, name, lambda: _download_pdf(url))
    return {
        "path": str(path),
        "pdf_path_property": brain.pdf_path(name) if brain else None,
        "paper_id": paper_id,
        "url": url,
        "bytes": path.stat().st_size,
    }
