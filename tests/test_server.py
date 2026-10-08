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
    assert set(tools["fetch_pdf"]["properties"]) == {"identifier", "paper_id", "dest_dir"}
    assert tools["trust_check"]["required"] == ["identifier"]
    assert {"paper_id", "title", "topic", "verdict", "key_points"} <= set(tools["prepare_ingest"]["required"])


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
