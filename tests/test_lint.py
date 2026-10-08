from datetime import date

from conftest import paper_page

from sci_paper_mcp.lint import lint

TODAY = date(2026, 10, 8)


def findings(brain, check=None):
    out = lint(brain, today=TODAY)["findings"]
    return [f for f in out if check is None or f["check"] == check]


def test_healthy_brain_has_no_findings(healthy_brain):
    assert findings(healthy_brain) == []


def test_missing_required_property_is_reported(make_brain):
    brain = make_brain(
        pages={"Sources/Research/X": paper_page(drop=["trustworthiness"])},
        assets=["RAG-Lewis2020-2005.11401.pdf"],
    )
    [f] = findings(brain, "schema")
    assert f["page"] == "Sources/Research/X"
    assert "trustworthiness" in f["message"]


def test_topic_outside_taxonomy_is_reported(make_brain):
    brain = make_brain(
        pages={"Sources/Research/X": paper_page({"topic": "cooking"})},
        assets=["RAG-Lewis2020-2005.11401.pdf"],
    )
    [f] = findings(brain, "schema")
    assert "cooking" in f["message"] and "taxonomy" in f["message"]


def test_triple_colon_property_is_reported(make_brain):
    brain = make_brain(
        pages={"Sources/Research/X": paper_page() + "\n- bad\n  topic::: rag-foundations\n"},
        assets=["RAG-Lewis2020-2005.11401.pdf"],
    )
    assert any(":::" in f["message"] for f in findings(brain, "schema"))


def test_pdf_path_pointing_nowhere_is_reported(make_brain):
    brain = make_brain(pages={"Sources/Research/X": paper_page()}, assets=[])
    [f] = findings(brain, "pdf")
    assert f["page"] == "Sources/Research/X" and "RAG-Lewis2020-2005.11401.pdf" in f["message"]


def test_pdf_path_not_found_marker_is_not_a_file_error(make_brain):
    brain = make_brain(pages={"Sources/Research/X": paper_page({"pdf-path": "not-found"})})
    assert findings(brain, "pdf") == []


def test_page_nobody_links_to_is_reported(make_brain):
    brain = make_brain(
        pages={"Sources/Research/X": paper_page(), "Concepts/RAG": "- nothing here\n"},
        assets=["RAG-Lewis2020-2005.11401.pdf"],
    )
    [f] = findings(brain, "links")
    assert f["page"] == "Sources/Research/X" and "no backlinks" in f["message"]


def test_related_page_that_does_not_exist_is_reported(make_brain):
    body = "- # T\n\t- ## Related Pages\n\t\t- [[Concepts/Ghost]]\n"
    brain = make_brain(
        pages={"Sources/Research/X": paper_page(body=body), "Concepts/Y": "- [[Sources/Research/X]]"},
        assets=["RAG-Lewis2020-2005.11401.pdf"],
    )
    [f] = findings(brain, "links")
    assert "Concepts/Ghost" in f["message"]


def test_empty_highlights_embed_is_a_todo_not_an_error(make_brain):
    body = "- # T\n\t- ## Highlights\n\t\t- {{embed [[hls__RAG-Lewis2020-2005.11401]]}}\n"
    brain = make_brain(
        pages={"Sources/Research/X": paper_page(body=body), "Concepts/Y": "- [[Sources/Research/X]]"},
        assets=["RAG-Lewis2020-2005.11401.pdf"],
    )
    [f] = findings(brain, "highlights")
    assert f["severity"] == "todo" and "hls__RAG-Lewis2020-2005.11401" in f["message"]


def test_annotated_highlights_are_not_reported(make_brain):
    body = "- # T\n\t- ## Highlights\n\t\t- {{embed [[hls__H]]}}\n"
    brain = make_brain(
        pages={
            "Sources/Research/X": paper_page(body=body),
            "Concepts/Y": "- [[Sources/Research/X]]",
            "hls__H": "file:: x\n\n- a highlight\n  ls-type:: annotation\n",
        },
        assets=["RAG-Lewis2020-2005.11401.pdf"],
    )
    assert findings(brain, "highlights") == []


def test_needs_update_older_than_60_days_is_stale(make_brain):
    old = paper_page({"status": "needs-update", "date": "2026-07-01"})
    brain = make_brain(
        pages={"Sources/Research/X": old, "Concepts/Y": "- [[Sources/Research/X]]"},
        assets=["RAG-Lewis2020-2005.11401.pdf"],
    )
    [f] = findings(brain, "stale")
    assert "99 days" in f["message"]


def test_needs_update_within_60_days_is_fine(make_brain):
    fresh = paper_page({"status": "needs-update", "date": "2026-09-20"})
    brain = make_brain(
        pages={"Sources/Research/X": fresh, "Concepts/Y": "- [[Sources/Research/X]]"},
        assets=["RAG-Lewis2020-2005.11401.pdf"],
    )
    assert findings(brain, "stale") == []


def test_topic_list_drift_between_agents_and_templates_is_reported(make_brain):
    from conftest import TEMPLATES

    drifted = TEMPLATES.replace("rag-foundations | rag-retrieval", "rag-foundations")
    brain = make_brain(templates=drifted)
    [f] = findings(brain, "drift")
    assert "rag-retrieval" in f["message"] and "Templates" in f["message"]


def test_summary_counts_findings_per_check(make_brain):
    brain = make_brain(
        pages={
            "Sources/Research/A": paper_page({"topic": "x"}),
            "Sources/Research/B": paper_page(drop=["url"]),
            "Concepts/RAG": "- [[Sources/Research/A]] [[Sources/Research/B]]",
        },
        assets=["RAG-Lewis2020-2005.11401.pdf"],
    )
    result = lint(brain, today=TODAY)
    assert result["summary"] == {"schema": 2}


def test_lint_never_modifies_the_brain(healthy_brain):
    before = {p: p.read_bytes() for p in healthy_brain.rglob("*") if p.is_file()}
    lint(healthy_brain, today=TODAY)
    assert {p: p.read_bytes() for p in healthy_brain.rglob("*") if p.is_file()} == before


def index_page(*queries):
    return "- ## Sources\n" + "".join(f"\t- {{{{query {q}}}}}\n" for q in queries)


PAPER_QUERY = "(and (page-property source-type paper) (page-property topic rag-foundations))"


def index_brain(make_brain, index, **paper_overrides):
    return make_brain(
        pages={
            "Index": index,
            "Sources/Research/X": paper_page(paper_overrides),
            "Concepts/Y": "- [[Sources/Research/X]]",
        },
        assets=["RAG-Lewis2020-2005.11401.pdf"],
    )


def test_page_matched_by_an_index_query_is_covered(make_brain):
    brain = index_brain(make_brain, index_page(PAPER_QUERY))
    assert findings(brain, "index") == []


def test_page_matched_by_no_index_query_is_reported(make_brain):
    brain = index_brain(make_brain, index_page(PAPER_QUERY), topic="rag-retrieval")
    [f] = findings(brain, "index")
    assert f["page"] == "Sources/Research/X"
    assert "topic" in f["message"] and "rag-retrieval" in f["message"]


def test_single_property_query_covers_every_page_with_that_value(make_brain):
    brain = index_brain(make_brain, index_page("(page-property topic rag-retrieval)"), topic="rag-retrieval")
    assert findings(brain, "index") == []


def test_all_terms_of_an_and_query_must_match(make_brain):
    brain = index_brain(make_brain, index_page(PAPER_QUERY), **{"source-type": "book"})
    assert len(findings(brain, "index")) == 1


def test_query_with_unsupported_operators_is_flagged_as_not_understood(make_brain):
    brain = index_brain(make_brain, index_page(PAPER_QUERY, "(or (page-property topic a) (task TODO))"))
    [f] = findings(brain, "index")
    assert f["severity"] == "todo" and "not understood" in f["message"]


def test_triple_lowbar_file_without_pinned_format_is_reported(make_brain):
    brain = make_brain(raw_files={"Concepts___Foo.md": "- x"}, config_edn="{:preferred-format :markdown}")
    [f] = findings(brain, "files")
    assert f["severity"] == "warning" and "Concepts___Foo.md" in f["message"]
    assert "file-name-format" in f["message"]


def test_triple_lowbar_file_is_fine_when_the_format_is_pinned(make_brain):
    brain = make_brain(
        raw_files={"Concepts___Foo.md": "- x"}, config_edn="{:file-name-format :triple-lowbar}"
    )
    assert findings(brain, "files") == []


def test_triple_lowbar_file_without_any_logseq_config_is_reported(make_brain):
    brain = make_brain(raw_files={"Concepts___Foo.md": "- x"})
    assert len(findings(brain, "files")) == 1


def test_two_files_for_one_page_title_are_an_error(make_brain):
    brain = make_brain(
        raw_files={"Concepts___Foo.md": "- real", "Concepts%2FFoo.md": "- stray"},
        config_edn="{:file-name-format :triple-lowbar}",
    )
    [f] = findings(brain, "files")
    assert f["severity"] == "error" and f["page"] == "Concepts/Foo"
    assert "Concepts___Foo.md" in f["message"] and "Concepts%2FFoo.md" in f["message"]


def test_percent_encoded_files_alone_need_no_config(make_brain):
    brain = make_brain(raw_files={"Concepts%2FFoo.md": "- x"})
    assert findings(brain, "files") == []
