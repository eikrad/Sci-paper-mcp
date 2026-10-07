from datetime import date

import pytest

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
    base = dict(paper_id="RAG-Lewis2020", title="RAG", authors=["P. Lewis"], topic="rag-retrieval",
                verdict="HIGH", verdict_reasoning="NeurIPS", abstract="abs", key_points=["k"],
                relevance="r", related_pages=["Concepts/RAG"], arxiv_id="2005.11401",
                pdf_path="../assets/papers/RAG-Lewis2020-2005.11401.pdf", today=date(2026, 1, 2))
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
    assert tools == [("create_page", "Sources/Research/RAG-Lewis2020"),
                     ("update_page", "Concepts/RAG"), ("update_page", "Log")]
    create = r["calls"][0]["arguments"]
    assert create["properties"]["trustworthiness"] == "HIGH"
    assert "## Abstract" in create["content"] and "hls__RAG-Lewis2020-2005.11401" in create["content"]
    assert "## [2026-01-02] ingest | Sources/Research/RAG-Lewis2020" in r["calls"][-1]["arguments"]["content"]


@pytest.mark.parametrize("bad", [{"topic": "nope"}, {"verdict": "GREAT"}, {"language": "fr"},
                                 {"arxiv_id": None}])
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
