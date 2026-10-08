import json
from datetime import date

import httpx
import pytest
import respx

from sci_paper_mcp.ingest import prepare_ingest
from sci_paper_mcp.schema import SchemaError, load_schema

AGENTS = """# AGENTS
```
source-type::   paper | book | concept
topic::         rag-foundations | rag-retrieval
language::      en | da | de
status::        ingested | reviewed
```
"""
TEMPLATES = """## Templates
- ## Research Paper
template:: Research Paper
	- # <Title>
		- ## Abstract
			-
		- ## Key Points
			-
		- ## Verification
			-
		- ## Highlights
			-
- ### Research Paper — page-property block
"""


@pytest.fixture
def brain(tmp_path):
    (tmp_path / "pages").mkdir()
    (tmp_path / "AGENTS.md").write_text(AGENTS)
    (tmp_path / "pages" / "Templates.md").write_text(TEMPLATES)
    (tmp_path / "pages" / "Concepts%2FRAG.md").write_text("- x")
    return tmp_path


def args(**kw):
    base = dict(
        paper_id="RAG-Lewis2020",
        title="RAG",
        authors=["P. Lewis"],
        topic="rag-retrieval",
        verdict="HIGH",
        verdict_reasoning="NeurIPS",
        abstract="abs",
        key_points=["k"],
        relevance="r",
        related_pages=["Concepts/RAG"],
        arxiv_id="2005.11401",
        pdf_path="../assets/papers/RAG-Lewis2020-2005.11401.pdf",
        today=date(2026, 1, 2),
    )
    return base | kw


def test_schema_parsed_from_graph(brain):
    s = load_schema(brain)
    assert s.taxonomy == ["rag-foundations", "rag-retrieval"]
    assert s.sections == ["Abstract", "Key Points", "Verification", "Highlights"]


def test_missing_agents_md_is_hard_error(tmp_path):
    with pytest.raises(SchemaError, match="no schema"):
        load_schema(tmp_path)
    with pytest.raises(SchemaError, match="SECOND_BRAIN_PATH"):
        load_schema(None)


def test_prepare_renders_calls_in_order(brain):
    r = prepare_ingest(brain, **args())
    tools = [(c["tool"], c["arguments"].get("page_name") or c["arguments"]["title"]) for c in r["calls"]]
    assert tools == [
        ("create_page", "Sources/Research/RAG-Lewis2020"),
        ("update_page", "Concepts/RAG"),
        ("update_page", "Log"),
    ]
    create = r["calls"][0]["arguments"]
    assert create["properties"]["trustworthiness"] == "HIGH"
    assert "## Abstract" in create["content"] and "hls__RAG-Lewis2020-2005.11401" in create["content"]
    assert "## [2026-01-02] ingest | Sources/Research/RAG-Lewis2020" in r["calls"][-1]["arguments"]["content"]


@pytest.mark.parametrize(
    "bad", [{"topic": "nope"}, {"verdict": "GREAT"}, {"language": "fr"}, {"arxiv_id": None}]
)
def test_invalid_input_rejected(brain, bad):
    with pytest.raises(SchemaError):
        prepare_ingest(brain, **args(**bad))


def test_existing_page_rejected(brain):
    (brain / "pages" / "Sources%2FResearch%2FRAG-Lewis2020.md").write_text("- x")
    with pytest.raises(SchemaError, match="already exists"):
        prepare_ingest(brain, **args())


def test_missing_related_page_warns_and_skips_backlink(brain):
    r = prepare_ingest(brain, **args(related_pages=["Concepts/RAG", "Nope"]))
    assert any("Nope" in w for w in r["warnings"])
    assert [c["arguments"].get("page_name") for c in r["calls"][1:]] == ["Concepts/RAG", "Log"]


LOGSEQ = "http://localhost:12315"


@pytest.fixture
def logseq_env(monkeypatch):
    monkeypatch.setenv("LOGSEQ_API_URL", LOGSEQ)
    monkeypatch.setenv("LOGSEQ_API_TOKEN", "t0ken")


def open_graph(path):
    return respx.post(f"{LOGSEQ}/api").respond(json={"name": "g", "path": str(path)})


@respx.mock
def test_matching_open_graph_passes_without_warning(brain, logseq_env):
    route = open_graph(brain)
    r = prepare_ingest(brain, **args())
    assert not any("graph" in w.lower() for w in r["warnings"])
    sent = route.calls[0].request
    assert sent.headers["authorization"] == "Bearer t0ken"
    assert json.loads(sent.content)["method"] == "logseq.App.getCurrentGraph"


@respx.mock
def test_other_open_graph_refuses_to_prepare(brain, logseq_env, tmp_path_factory):
    other = tmp_path_factory.mktemp("radiation-brain")
    open_graph(other)
    with pytest.raises(SchemaError, match="wrong graph") as e:
        prepare_ingest(brain, **args())
    assert str(brain) in str(e.value) and str(other) in str(e.value)


@respx.mock
def test_path_comparison_ignores_symlinks_and_trailing_slash(brain, logseq_env, tmp_path_factory):
    link = tmp_path_factory.mktemp("links") / "brain-link"
    link.symlink_to(brain)
    open_graph(f"{link}/")
    prepare_ingest(brain, **args())


@respx.mock
def test_no_graph_open_in_logseq_refuses(brain, logseq_env):
    respx.post(f"{LOGSEQ}/api").respond(content="null")
    with pytest.raises(SchemaError, match="no graph is open"):
        prepare_ingest(brain, **args())


@respx.mock
def test_unreachable_logseq_warns_but_still_prepares(brain, logseq_env):
    respx.post(f"{LOGSEQ}/api").mock(side_effect=httpx.ConnectError("refused"))
    r = prepare_ingest(brain, **args())
    assert any("could not verify" in w for w in r["warnings"]) and r["calls"]


def test_missing_token_warns_without_calling_logseq(brain, monkeypatch):
    monkeypatch.delenv("LOGSEQ_API_TOKEN", raising=False)
    with respx.mock:  # any request would raise: nothing is mocked
        r = prepare_ingest(brain, **args())
    assert any("LOGSEQ_API_TOKEN" in w for w in r["warnings"])


def test_verification_can_be_skipped(brain, monkeypatch):
    monkeypatch.delenv("LOGSEQ_API_TOKEN", raising=False)
    r = prepare_ingest(brain, **args(), verify_graph=False)
    assert not any("LOGSEQ_API_TOKEN" in w for w in r["warnings"])


@respx.mock
def test_unreadable_logseq_answer_warns_instead_of_crashing(brain, logseq_env):
    respx.post(f"{LOGSEQ}/api").respond(content="<html>not the api</html>")
    r = prepare_ingest(brain, **args())
    assert any("could not verify" in w for w in r["warnings"])


@respx.mock
def test_rejected_token_warns_with_hint(brain, logseq_env):
    respx.post(f"{LOGSEQ}/api").respond(401)
    r = prepare_ingest(brain, **args())
    assert any("could not verify" in w and "401" in w for w in r["warnings"])
