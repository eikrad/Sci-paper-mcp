"""prepare_highlights: find the agent's passages in a paper's PDF and turn them into Logseq highlights.

The agent picks the passages (ADR 0001); the server only checks that each one is really in the PDF and
works out where. It writes the positions to `assets/<pdf-stem>.edn`, the file Logseq's PDF viewer draws
highlights from, and returns the `hls__` page for the agent to create through mcp-logseq (ADR 0002).
"""

import json
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from .brain import Brain, SchemaError, highlights_title, names_pdf, paper_title, parse_properties, pdf_stem

Box = tuple[float, float, float, float]  # x1, y1, x2, y2 from the page's top-left corner, in PDF points


@dataclass
class _Page:
    """One PDF page's text, flattened for matching, and where each character sits."""

    number: int  # 1-based, as Logseq counts
    size: tuple[float, float]
    key: str  # the page text, normalised for matching
    source: list[int]  # character index in the PDF of each character of `key`
    boxes: list[Box | None]  # by character index; None for blanks


def _normalise(ch: str) -> str:
    return "" if ch.isspace() else ch


def _key(text: str) -> str:
    return "".join(_normalise(ch) for ch in text)


def _read(pdf_file: Path) -> list[_Page]:
    pdf = pdfium.PdfDocument(pdf_file)
    try:
        pages = []
        for index in range(len(pdf)):
            page = pdf[index]
            left, bottom, right, top = page.get_cropbox()
            text = page.get_textpage()
            key, source, boxes = [], [], []
            for i in range(text.count_chars()):
                code = pdfium_c.FPDFText_GetUnicode(text, i)
                normal = _normalise(chr(code)) if code else ""
                key.append(normal)
                source += [i] * len(normal)
                if normal:
                    x1, y1, x2, y2 = text.get_charbox(i, loose=True)  # PDF space: y grows upwards
                    boxes.append((x1 - left, top - y2, x2 - left, top - y1))
                else:
                    boxes.append(None)
            pages.append(_Page(index + 1, (right - left, top - bottom), "".join(key), source, boxes))
            text.close()
            page.close()
        return pages
    finally:
        pdf.close()


def _union(a: Box, b: Box) -> Box:
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def _lines(boxes: list[Box]) -> list[Box]:
    """One rectangle per text line: a character joins the line its vertical centre falls in."""
    lines: list[Box] = []
    for box in boxes:
        centre = (box[1] + box[3]) / 2
        if lines and lines[-1][1] <= centre <= lines[-1][3]:
            lines[-1] = _union(lines[-1], box)
        else:
            lines.append(box)
    return lines


def _find(pages: list[_Page], passage: str) -> tuple[_Page, list[Box]] | None:
    key = _key(passage)
    for page in pages:
        if key and (start := page.key.find(key)) >= 0:
            first, last = page.source[start], page.source[start + len(key) - 1]
            return page, _lines([b for b in page.boxes[first : last + 1] if b])
    return None


# --- Logseq's formats --------------------------------------------------------------------------------


def _edn(value) -> str:
    """EDN for the shapes Logseq's highlight file uses. Dict keys are written as keywords."""
    match value:
        case dict():
            return "{" + ", ".join(f":{k} {_edn(v)}" for k, v in value.items()) + "}"
        case list():
            return "[" + " ".join(_edn(v) for v in value) + "]"
        case tuple():
            return "(" + " ".join(_edn(v) for v in value) + ")"
        case uuid.UUID():
            return f'#uuid "{value}"'
        case str():
            return json.dumps(value, ensure_ascii=False)
        case float():
            return repr(round(value, 3))
        case int():
            return str(value)
    raise TypeError(f"no EDN form for {type(value).__name__}")


def _position(page: _Page, rects: list[Box]) -> dict:
    width, height = page.size

    def box(b: Box) -> dict:
        return {"x1": b[0], "y1": b[1], "x2": b[2], "y2": b[3], "width": width, "height": height}

    bounding = rects[0]
    for r in rects[1:]:
        bounding = _union(bounding, r)
    return {"bounding": box(bounding), "rects": tuple(box(r) for r in rects), "page": page.number}


def _block(text: str, page: int, color: str, id_: uuid.UUID) -> str:
    return f"- {text}\n  ls-type:: annotation\n  hl-page:: {page}\n  hl-color:: {color}\n  id:: {id_}"


def prepare_highlights(
    root: Path | None,
    *,
    paper_id: str,
    passages: list[str],
    color: str = "blue",
    today: date | None = None,
) -> dict:
    """Locate each passage in the paper's PDF, write the highlight file, return the hls__ page calls."""
    brain = Brain(root)
    title = paper_title(paper_id)
    page_text = brain.page(title)
    if page_text is None:
        raise SchemaError(f"no page '{title}'")
    pdf = parse_properties(page_text).get("pdf-path")
    if not names_pdf(pdf) or not brain.has_pdf(pdf):
        raise SchemaError(f"'{title}' has no PDF in the raw layer (pdf-path: {pdf})")

    pages = _read(brain.pdf_file(pdf))
    found, rejected, stored, blocks = [], [], [], []
    for passage in passages:
        text = " ".join(passage.split())
        hit = _find(pages, text)
        if hit is None:
            rejected.append({"passage": passage, "reason": "not found in the PDF"})
            continue
        page, rects = hit
        id_ = uuid.uuid4()
        found.append({"id": str(id_), "page": page.number, "text": text})
        stored.append(
            {
                "id": id_,
                "page": page.number,
                "position": _position(page, rects),
                "content": {"text": text},
                "properties": {"color": color},
            }
        )
        blocks.append(_block(text, page.number, color, id_))

    hls = highlights_title(pdf)
    brain.highlights_file(pdf).write_text(_edn({"highlights": stored, "extra": {"page": 1}}) + "\n")
    today = today or date.today()
    calls = [
        {
            "tool": "create_page",
            "arguments": {
                "title": hls,
                "properties": {"file": f"[{pdf_stem(pdf)}.pdf]({pdf})", "file-path": pdf},
                "content": "\n".join(blocks),
            },
        },
        {
            "tool": "update_page",
            "arguments": {
                "page_name": "Log",
                "mode": "append",
                "content": (
                    f"## [{today.isoformat()}] highlights | {title}\n"
                    f"- {len(found)} highlight(s) in {color} on [[{hls}]]; "
                    f"{len(rejected)} passage(s) rejected"
                ),
            },
        },
    ]
    return {"page": hls, "highlights": found, "rejected": rejected, "calls": calls, "warnings": []}
