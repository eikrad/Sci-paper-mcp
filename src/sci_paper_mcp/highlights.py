"""prepare_highlights: find the agent's passages in a paper's PDF and turn them into Logseq highlights.

The agent picks the passages (ADR 0001); the server only checks that each one is really in the PDF and
works out where. It writes the positions to `assets/<pdf-stem>.edn`, the file Logseq's PDF viewer draws
highlights from, and returns the `hls__` page for the agent to create through mcp-logseq (ADR 0002).
"""

import json
import unicodedata
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


COLORS = ("yellow", "red", "green", "blue", "purple")  # the colours of Logseq's highlight menu

_QUOTES = str.maketrans("\u2018\u2019\u201a\u201b\u2032\u201c\u201d\u201e\u201f\u2033", "'''''\"\"\"\"\"")
# Hyphens and dashes are ignored along with blanks: a line break can hide a compound's hyphen or add one
# inside a word, and PDFium reports a hyphen at a line break as U+0002.
_IGNORED = frozenset("-\u00ad\u2010\u2011\u2012\u2013\u2014\u2015\u2212\x02")


def _normalise(ch: str) -> str:
    """What a character counts as when matching.

    Ligatures and maths letters become plain letters (NFKC), quotes are straightened and case is ignored
    (small caps are often set as capitals); blanks, hyphens and dashes are dropped.
    """
    return "".join(
        c
        for c in unicodedata.normalize("NFKC", ch).translate(_QUOTES).casefold()
        if not c.isspace() and c not in _IGNORED
    )


def _key(text: str) -> str:
    return "".join(_normalise(ch) for ch in text)


def _char(codes: list[int], i: int) -> str:
    """The character at PDFium char index i.

    PDFium hands out UTF-16 code units, so a character outside the BMP (maths letters such as the
    italic tau) arrives as two indices: the pair is read at the first, the second counts as nothing.
    """
    code = codes[i]
    if 0xD800 <= code < 0xDC00 and i + 1 < len(codes) and 0xDC00 <= codes[i + 1] < 0xE000:
        return chr(0x10000 + ((code - 0xD800) << 10) + (codes[i + 1] - 0xDC00))
    if not code or 0xD800 <= code < 0xE000:
        return ""
    return chr(code)


def _read(pdf_file: Path) -> list[_Page]:
    pdf = pdfium.PdfDocument(pdf_file)
    try:
        pages = []
        for index in range(len(pdf)):
            page = pdf[index]
            left, bottom, right, top = page.get_cropbox()
            text = page.get_textpage()
            key, source, boxes = [], [], []
            codes = [pdfium_c.FPDFText_GetUnicode(text, i) for i in range(text.count_chars())]
            for i in range(len(codes)):
                normal = _normalise(_char(codes, i))
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


def _occurrences(pages: list[_Page], key: str) -> list[tuple[_Page, int]]:
    hits = []
    for page in pages:
        start = page.key.find(key)
        while start >= 0:
            hits.append((page, start))
            start = page.key.find(key, start + 1)
    return hits


def _locate(pages: list[_Page], text: str) -> tuple[str, list[tuple[_Page, int]]]:
    """The matching key of a passage and where it occurs.

    A passage whose final punctuation is the only difference also counts: agents drop inline citations,
    so "... memory [38]." gets quoted as "... memory.", and the highlight then ends at "memory".
    """
    key = _key(text)
    hits = _occurrences(pages, key) if key else []
    if not hits and (bare := key.rstrip(".,;:")) != key and bare:
        key, hits = bare, _occurrences(pages, bare)
    return key, hits


def _rects(page: _Page, start: int, length: int) -> list[Box]:
    first, last = page.source[start], page.source[start + length - 1]
    return _lines([b for b in page.boxes[first : last + 1] if b])


_NOT_FOUND = "not found on any one page of the PDF; a passage must be verbatim and lie on one page"


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
    """Locate each passage in the paper's PDF, write the highlight file, return the hls__ page calls.

    Only papers without highlights are touched: an existing edn or hls__ page is refused, since Logseq
    may hold the edn in memory and overwrite it. Nothing is written when no passage is found.
    """
    if not passages:
        raise SchemaError("give at least one passage")
    if color not in COLORS:
        raise SchemaError(f"colour '{color}' is not one of Logseq's highlight colours {COLORS}")
    brain = Brain(root)
    title = paper_title(paper_id)
    page_text = brain.page(title)
    if page_text is None:
        raise SchemaError(f"no page '{title}'")
    pdf = parse_properties(page_text).get("pdf-path")
    if not names_pdf(pdf) or not brain.has_pdf(pdf):
        raise SchemaError(f"'{title}' has no PDF in the raw layer (pdf-path: {pdf})")
    hls, edn_file = highlights_title(pdf), brain.highlights_file(pdf)
    if edn_file.exists() or brain.has_page(hls):
        raise SchemaError(f"'{title}' already has highlights ({hls}); they are left alone")

    pages = _read(brain.pdf_file(pdf))
    found, rejected, stored, blocks, warnings = [], [], [], [], []
    for passage in passages:
        text = " ".join(passage.split())
        key, hits = _locate(pages, text)
        if not hits:
            rejected.append({"passage": passage, "reason": _NOT_FOUND})
            continue
        page, start = hits[0]
        if len(hits) > 1:
            warnings.append(
                f"found {len(hits)} times, highlighted the first (page {page.number}): {text[:60]}"
            )
        id_ = uuid.uuid4()
        found.append({"id": str(id_), "page": page.number, "text": text})
        stored.append(
            {
                "id": id_,
                "page": page.number,
                "position": _position(page, _rects(page, start, len(key))),
                "content": {"text": text},
                "properties": {"color": color},
            }
        )
        blocks.append(_block(text, page.number, color, id_))

    result = {"page": hls, "highlights": found, "rejected": rejected, "warnings": warnings}
    if not found:
        return result | {"calls": [], "next": "No passage was found, so nothing was written."}
    edn_file.write_text(_edn({"highlights": stored, "extra": {"page": 1}}) + "\n")
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
    return result | {
        "calls": calls,
        "next": (
            f"{edn_file.name} is written. Apply `calls` in order with mcp-logseq; until then Logseq shows "
            "the highlights on the PDF without their blocks."
        ),
    }
