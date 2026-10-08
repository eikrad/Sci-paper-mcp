"""The Brain: the graph on disk and the paper-page format shared by ingest, lint and fetch_pdf."""

from datetime import date

import pytest
from conftest import AGENTS, TEMPLATES, apply_calls, ingest_args

from sci_paper_mcp.brain import (
    Brain,
    SchemaError,
    embedded_highlights,
    highlights_embed,
    pdf_name,
    resolve_paper_id,
    save_pdf,
)
from sci_paper_mcp.ingest import prepare_ingest
from sci_paper_mcp.lint import lint

TODAY = date(2026, 10, 8)
PAGE = "Sources/Research/RAG-Lewis2020"


def schema_of(root):
    return Brain(root).schema


def test_schema_parsed_from_graph(make_brain):
    s = schema_of(make_brain())
    assert s.taxonomy == ["rag-foundations", "rag-retrieval"]
    assert s.sections == [
        "Abstract",
        "Key Points",
        "Relevance to This Project",
        "Related Pages",
        "Verification",
        "Highlights",
        "Local PDF",
    ]
    assert s.template_topics == ["rag-foundations", "rag-retrieval"]


def test_missing_agents_md_is_hard_error(tmp_path):
    with pytest.raises(SchemaError, match="no schema"):
        schema_of(tmp_path)
    with pytest.raises(SchemaError, match="SECOND_BRAIN_PATH"):
        Brain(None)


@pytest.mark.parametrize(
    "agents,templates,message",
    [
        pytest.param("# AGENTS\n", TEMPLATES, "no 'source-type::' line", id="agents-lacks-a-property"),
        pytest.param(AGENTS, None, "Templates.md not found", id="no-templates-page"),
        pytest.param(AGENTS, "- nothing\n", "no 'Research Paper' template", id="no-paper-template"),
        pytest.param(
            AGENTS, "## Research Paper\n- ### page-property block\n", "no '##' sections", id="no-sections"
        ),
    ],
)
def test_unusable_schema_is_a_hard_error_with_a_clear_message(make_brain, agents, templates, message):
    brain = make_brain(agents=agents, templates=templates or "")
    if templates is None:
        (brain / "pages" / "Templates.md").unlink()
    with pytest.raises(SchemaError, match=message):
        schema_of(brain)


@pytest.mark.parametrize("filename", ["Sources%2FResearch%2FX.md", "Sources___Research___X.md"])
def test_page_titles_and_file_names_map_both_ways_for_either_separator(make_brain, filename):
    root = make_brain()
    (root / "pages" / filename).write_text("- x")
    brain = Brain(root)
    assert brain.pages()["Sources/Research/X"] == "- x" and "Templates" in brain.pages()
    assert brain.page("Sources/Research/X") == "- x" and brain.has_page("Sources/Research/X")
    assert brain.page("Sources/Research/Y") is None and not brain.has_page("Sources/Research/Y")


def test_saving_a_pdf_never_overwrites(tmp_path):
    save_pdf(tmp_path, "X.pdf", lambda: b"%PDF-1")

    def must_not_download():
        raise AssertionError("downloaded although the file exists")

    with pytest.raises(RuntimeError, match="already exists"):
        save_pdf(tmp_path, "X.pdf", must_not_download)

    def appears_meanwhile():
        (tmp_path / "Y.pdf").write_bytes(b"theirs")
        return b"%PDF-mine"

    with pytest.raises(RuntimeError, match="already exists"):
        save_pdf(tmp_path, "Y.pdf", appears_meanwhile)
    assert (tmp_path / "X.pdf").read_bytes() == b"%PDF-1" and (tmp_path / "Y.pdf").read_bytes() == b"theirs"


def test_a_brain_without_agents_md_can_still_take_a_pdf(tmp_path):
    brain = Brain(tmp_path)
    assert brain.find_pdf("X", arxiv_id="1") is None  # not even a raw layer yet
    path = save_pdf(brain.raw_layer, "X-1.pdf", lambda: b"%PDF-1")
    assert path == tmp_path / "assets" / "papers" / "X-1.pdf"
    assert brain.pdf_path("X-1.pdf") == "../assets/papers/X-1.pdf"
    assert brain.has_pdf(brain.pdf_path("X-1.pdf"))
    assert brain.find_pdf("X", arxiv_id="1") == "../assets/papers/X-1.pdf"
    with pytest.raises(SchemaError, match="no schema"):
        schema_of(tmp_path)


def test_a_pdf_path_is_followed_from_pages_and_the_placeholder_points_nowhere(make_brain):
    brain = Brain(make_brain(assets=["X-1.pdf"]))
    assert brain.has_pdf("../assets/papers/X-1.pdf")
    assert not brain.has_pdf("../assets/papers/Y.pdf") and not brain.has_pdf("not-found")


@pytest.mark.parametrize(
    "ids,expected",
    [
        pytest.param({"arxiv_id": "2005.11401"}, "RAG-Lewis2020-2005.11401.pdf", id="arxiv"),
        pytest.param({"doi": "10.1/x"}, "RAG-Lewis2020-10.1_x.pdf", id="doi-only"),
        pytest.param(
            {"arxiv_id": "hep-th/9901001"}, "RAG-Lewis2020-hep-th_9901001.pdf", id="old-style-arxiv"
        ),
        pytest.param(
            {"arxiv_id": "2005.11401", "doi": "10.1/x"}, "RAG-Lewis2020-2005.11401.pdf", id="arxiv-wins"
        ),
        pytest.param({"s2_id": "abc123"}, "RAG-Lewis2020-abc123.pdf", id="s2"),
        pytest.param({}, "RAG-Lewis2020-unknown.pdf", id="no-id"),
    ],
)
def test_the_pdf_of_a_paper_has_one_name(ids, expected):
    assert pdf_name("RAG-Lewis2020", **ids) == expected


IDS = {"arxiv_id": "2005.11401", "doi": "10.1/X", "s2_id": "abc"}


@pytest.mark.parametrize(
    "assets,paper_id,expected",
    [
        pytest.param(
            ["RAG-Lewis2020-2005.11401.pdf"], "RAG-Lewis2020", "RAG-Lewis2020-2005.11401.pdf", id="arxiv"
        ),
        pytest.param(["RAG-Lewis2020-10.1_X.pdf"], "RAG-Lewis2020", "RAG-Lewis2020-10.1_X.pdf", id="doi"),
        pytest.param(
            ["RAG-Lewis2020-10.1_x.pdf"], "RAG-Lewis2020", "RAG-Lewis2020-10.1_x.pdf", id="doi-in-other-case"
        ),
        pytest.param(["RAG-Lewis2020-abc.pdf"], "RAG-Lewis2020", "RAG-Lewis2020-abc.pdf", id="s2"),
        pytest.param(
            ["RAG-Lewis2020-abc.pdf", "RAG-Lewis2020-10.1_x.pdf", "RAG-Lewis2020-2005.11401.pdf"],
            "RAG-Lewis2020",
            "RAG-Lewis2020-2005.11401.pdf",
            id="arxiv-before-doi-before-s2",
        ),
        pytest.param(["RAG-Lewis2020-2005.11401.pdf"], "RAG", None, id="paper-id-is-not-a-prefix"),
        pytest.param(["RAG-Lewis2020-9999.pdf"], "RAG-Lewis2020", None, id="other-paper"),
        pytest.param([], "RAG-Lewis2020", None, id="empty-raw-layer"),
    ],
)
def test_a_pdf_is_found_in_the_raw_layer_under_any_of_the_papers_ids(make_brain, assets, paper_id, expected):
    found = Brain(make_brain(assets=assets)).find_pdf(paper_id, **IDS)
    assert found == (f"../assets/papers/{expected}" if expected else None)


def test_paper_id_is_the_agents_made_file_safe_else_first_author_and_year():
    assert resolve_paper_id("RAG Lewis/2020", [], None) == "RAG_Lewis_2020"
    assert resolve_paper_id(None, ["Patrick Lewis", "B. Other"], 2020) == "Lewis2020"
    with pytest.raises(RuntimeError, match="pass paper_id"):
        resolve_paper_id(None, [], 2020)


def test_highlights_embed_is_read_back_from_a_page():
    block = highlights_embed("../assets/papers/X-1.pdf")
    assert block == "{{embed [[hls__X-1]]}}"
    page = f"- ## Highlights\n\t- {block}\n- {highlights_embed('Y-2.pdf')}\n- [[hls__Z]]"
    assert embedded_highlights(page) == ["hls__X-1", "hls__Y-2"]


@pytest.mark.parametrize(
    "assets",
    [
        pytest.param(["RAG-Lewis2020-2005.11401.pdf"], id="pdf-in-raw-layer"),
        pytest.param([], id="pdf-not-found"),
    ],
)
def test_a_page_written_by_prepare_ingest_passes_lint(make_brain, assets):
    """Writer and checker agree on the paper-page format: only 'no highlights yet' is left to do."""
    brain = make_brain(pages={"Concepts/RAG": "- x"}, assets=assets)
    result = prepare_ingest(brain, **ingest_args(), verify_graph=False)
    apply_calls(brain, result["calls"])

    findings = lint(brain, today=TODAY)["findings"]
    assert [(f["check"], f["severity"], f["page"]) for f in findings] == [("highlights", "todo", PAGE)], (
        findings
    )
    assert "hls__RAG-Lewis2020-2005.11401" in findings[0]["message"]
    assert (brain / "pages" / "Log.md").exists()
