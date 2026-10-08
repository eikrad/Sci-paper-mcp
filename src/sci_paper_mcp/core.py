"""The three phase-1 tools as plain functions; CLI and MCP both call these."""

import re
import tomllib
from pathlib import Path

import httpx

from . import config, sources
from .sources import Paper

UNPAYWALL_API = "https://api.unpaywall.org/v2"


def _dedupe(papers: list[Paper]) -> list[Paper]:
    """Merge by arXiv id / DOI / title; Semantic Scholar entries win (richer metadata)."""
    seen: dict[str, Paper] = {}
    for p in sorted(papers, key=lambda p: p.source != "semantic_scholar"):
        keys = [k for k in (p.arxiv_id, p.doi and p.doi.lower(), p.title.lower().strip()) if k]
        hit = next((seen[k] for k in keys if k in seen), None)
        if hit is None:
            hit = p
        else:
            hit.arxiv_id = hit.arxiv_id or p.arxiv_id
            hit.doi = hit.doi or p.doi
            hit.pdf_url = hit.pdf_url or p.pdf_url
        for k in keys:
            seen[k] = hit
    unique: list[Paper] = []
    for p in seen.values():
        if p not in unique:
            unique.append(p)
    return unique


def search_papers(
    query: str, limit: int = 10, sources_: tuple[str, ...] = ("arxiv", "semantic_scholar")
) -> dict:
    found: list[Paper] = []
    errors = []
    searchers = {"arxiv": sources.search_arxiv, "semantic_scholar": sources.search_semantic_scholar}
    for name in sources_:
        try:
            found += searchers[name](query, limit)
        except httpx.HTTPError as e:  # one source down must not kill the search
            errors.append(f"{name}: {e}")
    results = [p.to_dict() for p in _dedupe(found)[:limit]]
    if errors and not results:
        raise RuntimeError("; ".join(errors))
    return {"results": results, "warnings": errors}


def _venues() -> dict:
    with (Path(__file__).parent / "venues.toml").open("rb") as f:
        return tomllib.load(f)


def _matches(venue: str, needles: list[str]) -> bool:
    return any(re.search(n, venue, re.I) for n in needles)


def _try(fn, name: str, warnings: list[str]):
    """Run a lookup; a failing or missing source becomes a warning, not an error."""
    try:
        return fn()
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:
            warnings.append(f"{name}: {e}")
        return None
    except httpx.HTTPError as e:
        warnings.append(f"{name}: {e}")
        return None


def trust_check(identifier: str) -> dict:
    """Propose a HIGH/MEDIUM/LOW verdict from Semantic Scholar and OpenAlex together.

    Semantic Scholar supplies venue, citations and author h-index; OpenAlex adds the
    retraction flag and the source type. Either may be missing. A proposal, not a ruling.
    """
    warnings: list[str] = []
    d = _try(
        lambda: sources.get_s2_paper(identifier, "influentialCitationCount,authors.hIndex"),
        "semantic_scholar",
        warnings,
    )
    p = sources._from_s2(d) if d else None
    oa_id = sources.openalex_work_id(identifier, p.doi if p else None)
    oa = _try(lambda: sources.get_openalex_work(oa_id), "openalex", warnings) if oa_id else None

    if d is None and oa is None:
        if warnings:
            raise RuntimeError("; ".join(warnings))
        return {"verdict": "LOW", "reasons": ["not found on Semantic Scholar or OpenAlex"], "found": False}

    loc_source = ((oa or {}).get("primary_location") or {}).get("source") or {}
    source_type = loc_source.get("type")  # journal | conference | repository | ...
    venue = ((p.venue if p else None) or "").strip()
    if not venue and source_type in ("journal", "conference"):
        venue = loc_source.get("display_name") or ""
    preprint = (
        venue.lower() in ("", "arxiv", "arxiv.org", "arxiv e-prints")
        or source_type == "repository"
        and not venue
    )
    authors = p.authors if p else []
    arxiv_id = (p.arxiv_id if p else None) or (
        sources.s2_identifier(identifier)[6:]
        if sources.s2_identifier(identifier).startswith("ARXIV:")
        else None
    )
    h_values = [a["hIndex"] for a in (d or {}).get("authors") or [] if a.get("hIndex") is not None]
    max_h = max(h_values, default=None)
    retracted = bool((oa or {}).get("is_retracted"))
    venues = _venues()
    reasons: list[str] = []

    if retracted:
        verdict = "LOW"
        reasons.append("retracted according to OpenAlex")
    elif not preprint and _matches(venue, venues["suspect"]):
        verdict = "LOW"
        reasons.append(f"venue '{venue}' is on the suspect list")
    elif not preprint and _matches(venue, venues["reputable"]) and authors:
        verdict = "HIGH"
        reasons.append(f"peer-reviewed at reputable venue '{venue}'")
    elif not preprint:
        verdict = "MEDIUM"
        reasons.append(f"venue '{venue}' is not on the reputable list (mid-tier or unknown)")
    elif arxiv_id and max_h is not None and max_h >= 10:
        verdict = "MEDIUM"
        reasons.append(f"arXiv preprint; best author h-index {max_h}")
    elif arxiv_id:
        verdict = "LOW"
        reasons.append("arXiv preprint without verifiable established authors")
    else:
        verdict = "LOW"
        reasons.append("no venue and no arXiv id")
    if d is not None and not authors:
        reasons.append("no authors listed")
    if oa is None:
        reasons.append("retraction status unknown (OpenAlex unavailable)")

    return {
        "verdict": verdict,
        "reasons": reasons,
        "warnings": warnings,
        "found": True,
        "title": (p.title if p else None) or (oa or {}).get("display_name"),
        "year": (p.year if p else None) or (oa or {}).get("publication_year"),
        "venue": venue or None,
        "peer_reviewed": not preprint,
        "retracted": retracted if oa is not None else None,
        "source_type": source_type,
        "in_doaj": loc_source.get("is_in_doaj"),
        "citations": p.citations if p and p.citations is not None else (oa or {}).get("cited_by_count"),
        "citations_openalex": (oa or {}).get("cited_by_count"),
        "influential_citations": (d or {}).get("influentialCitationCount"),
        "max_author_h_index": max_h,
        "semantic_scholar_url": f"https://www.semanticscholar.org/paper/{p.s2_id}" if p and p.s2_id else None,
        "openalex_id": (oa or {}).get("id"),
    }


def _load_paper(identifier: str, paper_id: str | None) -> Paper:
    """Metadata for naming and PDF lookup; skips Semantic Scholar when the arXiv id suffices."""
    ident = sources.s2_identifier(identifier)
    if ident.startswith("ARXIV:") and paper_id:
        return Paper(title="", authors=[], arxiv_id=ident[6:])
    return sources._from_s2(sources.get_s2_paper(identifier))


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
