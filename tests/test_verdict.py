"""The verdict rules over plain Paper values: no HTTP."""

import pytest

from sci_paper_mcp import verdict
from sci_paper_mcp.sources import Paper
from sci_paper_mcp.verdict import is_preprint, propose_verdict


def paper(**fields) -> Paper:
    return Paper(**{"title": "T", "authors": ["A B"], "year": 2020} | fields)


@pytest.mark.parametrize(
    "venue,expected",
    [
        ("Conference on Empirical Methods in Natural Language Processing", "HIGH"),
        ("Annual Meeting of the Association for Computational Linguistics", "HIGH"),
        ("Social Science Computer Review", "MEDIUM"),
        ("Oracle Journal", "MEDIUM"),
        ("USENIX Security Symposium", "HIGH"),
        ("IEEE Symposium on Security and Privacy", "HIGH"),
        ("Conference on Computer and Communications Security", "HIGH"),
        ("ACM SIGSAC Conference on Computer and Communications Security", "HIGH"),
        ("Network and Distributed System Security Symposium", "HIGH"),
        ("Journal of Information Security and Applications", "MEDIUM"),
        ("Security and Communication Networks", "MEDIUM"),
        ("International Conference on Security and Privacy in Smart Cities", "MEDIUM"),
    ],
)
def test_venue_matching(venue, expected):
    assert propose_verdict(paper(venue=venue))[0] == expected


def test_high_for_reputable_venue():
    v, reasons = propose_verdict(paper(venue="Advances in NeurIPS", max_author_h_index=5))
    assert v == "HIGH" and not is_preprint(paper(venue="Advances in NeurIPS"))
    assert "reputable venue" in reasons[0]


def test_reputable_venue_needs_authors_to_be_high():
    v, reasons = propose_verdict(paper(venue="NeurIPS", authors=[]))
    assert v == "MEDIUM" and reasons[-1] == "no authors listed"


def test_medium_for_known_author_preprint():
    p = paper(venue="arXiv.org", arxiv_id="2005.11401", max_author_h_index=10)
    assert propose_verdict(p)[0] == "MEDIUM"


@pytest.mark.parametrize("h_index", [None, 9])
def test_low_for_unknown_preprint(h_index):
    assert propose_verdict(paper(arxiv_id="2005.11401", max_author_h_index=h_index))[0] == "LOW"


def test_low_without_venue_and_arxiv_id():
    v, reasons = propose_verdict(paper(max_author_h_index=50))
    assert v == "LOW" and reasons == ["no venue and no arXiv id"]


def test_retraction_forces_low():
    p = paper(venue="NeurIPS", max_author_h_index=50, retracted=True)
    v, reasons = propose_verdict(p)
    assert v == "LOW" and "retracted" in reasons[0]


def test_suspect_venue_forces_low(monkeypatch):
    monkeypatch.setattr(verdict, "_venues", lambda: {"suspect": ["predatory"], "reputable": ["predatory"]})
    v, reasons = propose_verdict(paper(venue="Predatory Press"))
    assert v == "LOW" and "suspect" in reasons[0]


@pytest.mark.parametrize(
    "venue,expected",
    [
        (None, True),
        ("arXiv.org", True),
        ("arXiv e-prints", True),
        ("Nature", False),
    ],
)
def test_is_preprint(venue, expected):
    assert is_preprint(paper(venue=venue)) is expected
