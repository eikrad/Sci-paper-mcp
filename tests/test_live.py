"""Smoke tests against the real APIs. Excluded from CI; run with `pytest -m live`."""

import pytest

from sci_paper_mcp import core

pytestmark = pytest.mark.live


def test_arxiv_search_returns_papers():
    out = core.search_papers("retrieval augmented generation", limit=3, sources_=("arxiv",))
    assert out["results"] and out["results"][0]["arxiv_id"]


def test_trust_check_reads_both_sources():
    out = core.trust_check("2005.11401")  # Lewis et al., RAG
    assert out["verdict"] in {"HIGH", "MEDIUM", "LOW"}
    assert out["retracted"] is False
