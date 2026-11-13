from datetime import date

import edn_format
import pytest
from conftest import page_file, paper_page
from pytest import approx
from reportlab.pdfgen import canvas

from sci_paper_mcp.brain import SchemaError
from sci_paper_mcp.highlights import prepare_highlights

STEM = "RAG-Lewis2020-2005.11401"
PASSAGE = "Retrieval helps language models stay factual."


def write_pdf(path, pages, size=(612, 792)):
    """A text PDF: `pages` is a list of pages, each a list of (x, baseline_y, text) lines in PDF points."""
    c = canvas.Canvas(str(path), pagesize=size)
    for lines in pages:
        c.setFont("Helvetica", 12)
        for x, y, text in lines:
            c.drawString(x, y, text)
        c.showPage()
    c.save()


def read_edn(path):
    """The highlights Logseq would read from an .edn file, as plain dicts."""
    data = edn_format.loads(path.read_text())
    k = edn_format.Keyword

    def box(m):
        return tuple(m[k(c)] for c in ("x1", "y1", "x2", "y2"))

    return [
        {
            "id": str(h[k("id")]),
            "page": h[k("page")],
            "bounding": box(h[k("position")][k("bounding")]),
            "rects": [box(r) for r in h[k("position")][k("rects")]],
            "size": (
                h[k("position")][k("bounding")][k("width")],
                h[k("position")][k("bounding")][k("height")],
            ),
            "text": h[k("content")][k("text")],
            "color": h[k("properties")][k("color")],
        }
        for h in data[k("highlights")]
    ]


@pytest.fixture
def brain(make_brain):
    return make_brain(pages={"Sources/Research/RAG-Lewis2020": paper_page()})


def pdf(brain):
    return brain / "assets" / "papers" / f"{STEM}.pdf"


def highlight(brain, passages, **kw):
    return prepare_highlights(
        brain, paper_id="RAG-Lewis2020", passages=passages, today=date(2026, 1, 2), **kw
    )


def test_a_passage_becomes_a_highlight_whose_block_logseq_can_find(brain):
    write_pdf(pdf(brain), [[(72, 700, PASSAGE)]])

    r = highlight(brain, [PASSAGE])

    assert r["rejected"] == []
    [h] = r["highlights"]
    assert h["page"] == 1
    create, log = r["calls"]
    assert create["tool"] == "create_page"
    assert create["arguments"]["title"] == f"hls__{STEM}"
    assert create["arguments"]["properties"] == {
        "file": f"[{STEM}.pdf](../assets/papers/{STEM}.pdf)",
        "file-path": f"../assets/papers/{STEM}.pdf",
    }
    assert create["arguments"]["content"] == (
        f"- {PASSAGE}\n  ls-type:: annotation\n  hl-page:: 1\n  hl-color:: blue\n  id:: {h['id']}"
    )
    [stored] = read_edn(brain / "assets" / f"{STEM}.edn")
    assert (stored["id"], stored["page"], stored["color"], stored["text"]) == (h["id"], 1, "blue", PASSAGE)
    assert stored["size"] == (612, 792)
    x1, y1, x2, y2 = stored["bounding"]  # Logseq measures from the top-left corner
    assert x1 == approx(72, abs=1) and x2 > 300
    assert 792 - 700 - 14 < y1 < y2 < 792 - 700 + 5
    assert log["tool"] == "update_page" and log["arguments"]["page_name"] == "Log"
    assert log["arguments"]["content"].startswith(
        "## [2026-01-02] highlights | Sources/Research/RAG-Lewis2020"
    )


# --- the passage only has to be verbatim, not typeset the same way ----------------------------------


def test_a_word_hyphenated_across_lines_is_found(brain):
    write_pdf(pdf(brain), [[(72, 700, "Dense retrieval keeps infor-"), (72, 686, "mation current.")]])
    r = highlight(brain, ["Dense retrieval keeps information current."])
    assert r["rejected"] == []
    [stored] = read_edn(brain / "assets" / f"{STEM}.edn")
    assert len(stored["rects"]) == 2  # one per line, as Logseq draws them


def test_a_compound_broken_at_its_hyphen_is_found(brain):
    write_pdf(pdf(brain), [[(72, 700, "We evaluate zero-"), (72, 686, "shot retrieval on BEIR.")]])
    assert highlight(brain, ["We evaluate zero-shot retrieval on BEIR."])["rejected"] == []


def test_quote_style_and_ligatures_do_not_matter(brain):
    write_pdf(pdf(brain), [[(72, 700, "Kendall’s tau confirms the final ranking.")]])
    r = highlight(brain, ["Kendall's tau conﬁrms the ﬁnal ranking."])
    assert r["rejected"] == []


def test_a_passage_that_is_not_in_the_pdf_is_rejected_and_the_rest_kept(brain):
    write_pdf(pdf(brain), [[(72, 700, PASSAGE)]])
    r = highlight(brain, [PASSAGE, "Retrieval makes language models stay factual."])
    assert [h["text"] for h in r["highlights"]] == [PASSAGE]
    [rejected] = r["rejected"]
    assert rejected["passage"] == "Retrieval makes language models stay factual."
    assert "not found" in rejected["reason"]
    assert len(read_edn(brain / "assets" / f"{STEM}.edn")) == 1


def test_a_passage_running_over_a_page_break_is_rejected(brain):
    write_pdf(pdf(brain), [[(72, 60, "The last line of a page")], [(72, 740, "continues on the next.")]])
    r = highlight(brain, ["The last line of a page continues on the next."])
    assert r["highlights"] == [] and "one page" in r["rejected"][0]["reason"]


def test_when_nothing_is_found_nothing_is_written(brain):
    write_pdf(pdf(brain), [[(72, 700, PASSAGE)]])
    r = highlight(brain, ["A sentence the paper never says."])
    assert r["calls"] == [] and r["highlights"] == []
    assert not (brain / "assets" / f"{STEM}.edn").exists()


def test_a_passage_that_occurs_twice_is_highlighted_once_with_a_warning(brain):
    write_pdf(pdf(brain), [[(72, 700, PASSAGE)], [(72, 700, PASSAGE)]])
    r = highlight(brain, [PASSAGE])
    assert [h["page"] for h in r["highlights"]] == [1]
    assert any("2 times" in w for w in r["warnings"])


# --- refusals: only papers without highlights, only real PDFs ----------------------------------------


def test_a_paper_that_already_has_highlights_is_left_alone(brain):
    write_pdf(pdf(brain), [[(72, 700, PASSAGE)]])
    (brain / "assets" / f"{STEM}.edn").write_text("{:highlights []}")
    with pytest.raises(SchemaError, match="already has highlights"):
        highlight(brain, [PASSAGE])
    assert (brain / "assets" / f"{STEM}.edn").read_text() == "{:highlights []}"


def test_a_paper_with_a_highlights_page_but_no_edn_is_left_alone(brain):
    write_pdf(pdf(brain), [[(72, 700, PASSAGE)]])
    page_file(brain, f"hls__{STEM}").write_text("- a hand-made note\n")
    with pytest.raises(SchemaError, match="already has highlights"):
        highlight(brain, [PASSAGE])


def test_a_paper_without_a_pdf_is_refused(make_brain):
    root = make_brain(pages={"Sources/Research/RAG-Lewis2020": paper_page({"pdf-path": "not-found"})})
    with pytest.raises(SchemaError, match="no PDF"):
        prepare_highlights(root, paper_id="RAG-Lewis2020", passages=[PASSAGE])


@pytest.mark.parametrize(
    "kw, match",
    [
        (dict(paper_id="Nobody2020"), "no page"),
        (dict(passages=[]), "at least one passage"),
        (dict(color="orange"), "colour"),
    ],
)
def test_bad_input_is_refused_before_anything_is_written(brain, kw, match):
    write_pdf(pdf(brain), [[(72, 700, PASSAGE)]])
    with pytest.raises(SchemaError, match=match):
        prepare_highlights(brain, **(dict(paper_id="RAG-Lewis2020", passages=[PASSAGE]) | kw))
    assert not (brain / "assets" / f"{STEM}.edn").exists()


def test_a_passage_that_drops_the_citation_before_its_full_stop_is_found(brain):
    write_pdf(pdf(brain), [[(72, 700, "Hybrid models combine both kinds of memory [38]. Next.")]])
    r = highlight(brain, ["Hybrid models combine both kinds of memory."])
    assert r["rejected"] == []
    [stored] = read_edn(brain / "assets" / f"{STEM}.edn")
    assert stored["bounding"][2] < 72 + 300  # ends at "memory", before the citation


def test_small_caps_set_in_capitals_are_found(brain):
    write_pdf(pdf(brain), [[(72, 700, "RAGCHECKER has the highest correlation.")]])
    assert highlight(brain, ["RAGChecker has the highest correlation."])["rejected"] == []
