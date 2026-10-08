"""The MCP surface agents actually see: tool names, parameters and a real call."""

import httpx
import pytest
import respx
from fastmcp import Client

from sci_paper_mcp import sources
from sci_paper_mcp.server import mcp


@pytest.fixture
async def client():
    async with Client(mcp) as c:
        yield c


async def test_tool_names_are_stable(client):
    names = {t.name for t in await client.list_tools()}
    assert names == {"search_papers", "trust_check", "fetch_pdf", "prepare_ingest", "lint"}


async def test_tool_parameters_are_stable(client):
    tools = {t.name: t.input_schema for t in await client.list_tools()}
    # no dest_dir: an agent steered by fetched text must not pick where files are written
    assert set(tools["fetch_pdf"]["properties"]) == {"identifier", "paper_id"}
    assert tools["trust_check"]["required"] == ["identifier"]
    ingest = tools["prepare_ingest"]
    assert set(ingest["properties"]) == {
        "identifier",
        "paper_id",
        "topic",
        "verdict",
        "verdict_reasoning",
        "key_points",
        "relevance",
        "related_pages",
        "language",
        "code_url",
        "abstract",
    }
    assert set(ingest["required"]) == {
        "identifier",
        "topic",
        "verdict",
        "verdict_reasoning",
        "key_points",
        "relevance",
        "related_pages",
    }


@respx.mock
async def test_search_papers_call_returns_results_and_warnings(client):
    respx.get(sources.ARXIV_API).respond(text="<feed xmlns='http://www.w3.org/2005/Atom'/>")
    respx.get(f"{sources.OPENALEX_API}/works").respond(json={"results": []})
    respx.get(f"{sources.S2_API}/paper/search").respond(
        json={"data": [{"paperId": "x", "title": "RAG", "year": 2020, "authors": []}]}
    )
    result = await client.call_tool("search_papers", {"query": "rag"})
    assert result.data["results"][0]["title"] == "RAG"
    assert result.data["warnings"] == []


@respx.mock
async def test_tool_errors_reach_the_agent_as_errors(client):
    respx.get(f"{sources.S2_API}/paper/DOI:10.1/x").mock(side_effect=httpx.ConnectError("down"))
    respx.get(url__startswith=f"{sources.OPENALEX_API}/works/").respond(500)
    with pytest.raises(Exception, match="semantic_scholar"):
        await client.call_tool("trust_check", {"identifier": "10.1/x"})


async def test_lint_tool_runs_against_the_configured_brain(client, healthy_brain, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_PATH", str(healthy_brain))
    result = await client.call_tool("lint", {})
    assert result.data["findings"] == []


@respx.mock
async def test_fetch_pdf_tool_saves_into_the_configured_brain(client, make_brain, monkeypatch):
    brain = make_brain()
    monkeypatch.setenv("SECOND_BRAIN_PATH", str(brain))
    respx.get("https://arxiv.org/pdf/2005.11401").respond(content=b"%PDF-1")
    result = await client.call_tool("fetch_pdf", {"identifier": "2005.11401", "paper_id": "X"})
    assert result.data["pdf_path_property"] == "../assets/papers/X-2005.11401.pdf"
    assert (brain / "assets" / "papers" / "X-2005.11401.pdf").exists()


@respx.mock
async def test_prepare_ingest_tool_looks_the_paper_up_and_finds_its_pdf(client, make_brain, monkeypatch):
    brain = make_brain(pages={"Concepts/RAG": "- x"}, assets=["Lewis2020-2005.11401.pdf"])
    monkeypatch.setenv("SECOND_BRAIN_PATH", str(brain))
    monkeypatch.delenv("LOGSEQ_API_TOKEN", raising=False)
    respx.get(f"{sources.S2_API}/paper/ARXIV:2005.11401").respond(
        json={
            "paperId": "p1",
            "title": "Retrieval-Augmented Generation",
            "year": 2020,
            "authors": [{"name": "Patrick Lewis", "hIndex": 30}],
            "venue": "NeurIPS",
            "externalIds": {"ArXiv": "2005.11401"},
            "citationCount": 5000,
            "abstract": "An abstract.",
        }
    )
    respx.get(url__startswith=f"{sources.OPENALEX_API}/works/").respond(
        json={
            "is_retracted": False,
            "cited_by_count": 18,  # split across preprint versions: never the page's citations
            "primary_location": {"source": {"type": "repository", "display_name": "arXiv"}},
        }
    )

    result = await client.call_tool(
        "prepare_ingest",
        {
            "identifier": "2005.11401",
            "topic": "rag-retrieval",
            "verdict": "HIGH",
            "verdict_reasoning": "NeurIPS",
            "key_points": ["k"],
            "relevance": "r",
            "related_pages": ["Concepts/RAG"],
        },
    )

    assert result.data["page"] == "Sources/Research/Lewis2020"
    create = result.data["calls"][0]["arguments"]
    assert create["properties"]["document-id"] == "arXiv:2005.11401"
    assert create["properties"]["pdf-path"] == "../assets/papers/Lewis2020-2005.11401.pdf"
    assert "# Retrieval-Augmented Generation" in create["content"]
    assert "- **Citations:** 5000" in create["content"] and "An abstract." in create["content"]
    assert any("LOGSEQ_API_TOKEN" in w for w in result.data["warnings"])
