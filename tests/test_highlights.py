from datetime import date

import edn_format
import pytest
from conftest import paper_page
from pytest import approx
from reportlab.pdfgen import canvas

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
