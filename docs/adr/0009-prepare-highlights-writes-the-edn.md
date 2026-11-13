# 0009 — prepare_highlights writes the highlight file; the hls__ page still goes through mcp-logseq

Status: accepted. Extends 0002.

A Logseq PDF highlight has two halves: the position, kept in `assets/<pdf-stem>.edn` (what the PDF viewer draws), and a block on the `hls__<pdf-stem>` page (what pages embed and link to). The edn entry and the block share one uuid; that is how Logseq ties them together.

`mcp-logseq` has no tool for files in `assets/`, so `prepare_highlights` writes the edn itself, as `fetch_pdf` writes PDFs. The page is returned as a call for the agent, as in 0002. Which call depends on whether Logseq already has the page: a paper page from `prepare_ingest` embeds `[[hls__<pdf-stem>]]`, and that link makes the page exist in Logseq without a file. `create_page` refuses such a page, and an `update_page` append puts the page properties on the first block, where Logseq does not look for `file-path`. `update_page` in replace mode writes them at the top, but refuses a page Logseq does not have. So the tool returns replace when any page links to the hls page, else `create_page`. All three behaviours were seen live on 2026-11-13, highlighting MCPGuard-Xing2025 in second-brain. mcp-logseq 1.10.0 keeps an `id::` passed in the content: checked live on 2026-11-13 against Logseq 0.10.15 (the block came back with the given uuid and the file Logseq wrote matched its own highlight-page format).

Only papers without highlights are touched. An existing edn or `hls__` page is refused, not merged: Logseq can hold an open PDF's edn in memory and write it back, which would drop lines added from outside. The open-graph check of 0006 runs before the edn is written, so the edn and the page land in the same brain.

The agent picks the passages (0001); the server only checks that each is in the PDF and places it. Matching ignores what typesetting changes and a reader does not: blanks, hyphens and dashes (PDFium reports a hyphen at a line break as U+0002), quote style, case (small caps set as capitals), ligatures and maths letters (NFKC), and a passage's final punctuation, since agents drop inline citations. On the 476 passages generated for second-brain in commit e3b533b, this finds all 476; whitespace-only matching found 292.

PDFs are read with pypdfium2 (Apache-2.0 / BSD-3-Clause). PyMuPDF has a richer search API but is AGPL-3.0, which does not fit this Apache-2.0 repository; the matching has to be our own anyway, because no library treats quote styles and dropped citations alike.

Not verified: whether Logseq draws the edn on a PDF it has never opened before without a restart. Positions are in PDF points from the crop box's top-left corner, the convention of the existing second-brain edn files (within 1–2 pt on the 476 passages). Rotated pages are not handled.
