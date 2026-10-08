"""The proposed Verdict (HIGH | MEDIUM | LOW) for a merged Paper; a pure function, no I/O but venues.toml."""

import re
import tomllib
from pathlib import Path
from typing import Literal

from .sources import Paper

Verdict = Literal["HIGH", "MEDIUM", "LOW"]
_PREPRINT_VENUES = ("", "arxiv", "arxiv.org", "arxiv e-prints")


def _venues() -> dict:
    with (Path(__file__).parent / "venues.toml").open("rb") as f:
        return tomllib.load(f)


def _matches(venue: str, needles: list[str]) -> bool:
    return any(re.search(n, venue, re.I) for n in needles)


def is_preprint(paper: Paper) -> bool:
    """No venue, or arXiv itself, so nobody peer-reviewed it. Adapters drop repositories as venues."""
    return (paper.venue or "").lower() in _PREPRINT_VENUES


def propose_verdict(paper: Paper) -> tuple[Verdict, list[str]]:
    """First matching rule wins; `reasons` says which. A proposal the agent may override."""
    venue = paper.venue or ""
    preprint = is_preprint(paper)
    venues = _venues()
    h_index = paper.max_author_h_index

    if paper.retracted:
        verdict, reason = "LOW", "retracted according to OpenAlex"
    elif not preprint and _matches(venue, venues["suspect"]):
        verdict, reason = "LOW", f"venue '{venue}' is on the suspect list"
    elif not preprint and _matches(venue, venues["reputable"]) and paper.authors:
        verdict, reason = "HIGH", f"peer-reviewed at reputable venue '{venue}'"
    elif not preprint:
        verdict, reason = "MEDIUM", f"venue '{venue}' is not on the reputable list (mid-tier or unknown)"
    elif paper.arxiv_id and h_index is not None and h_index >= 10:
        verdict, reason = "MEDIUM", f"arXiv preprint; best author h-index {h_index}"
    elif paper.arxiv_id:
        verdict, reason = "LOW", "arXiv preprint without verifiable established authors"
    else:
        verdict, reason = "LOW", "no venue and no arXiv id"
    reasons = [reason]
    if not paper.authors:
        reasons.append("no authors listed")
    return verdict, reasons
