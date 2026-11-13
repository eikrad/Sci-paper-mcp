"""Shared fixtures: build a throwaway Logseq brain on disk."""

from datetime import date

import pytest
from reportlab.pdfgen import canvas

from sci_paper_mcp import core
from sci_paper_mcp.core import Lookup
from sci_paper_mcp.sources import Paper

AGENTS = """# AGENTS
```
source-type::   paper | book | concept
topic::         rag-foundations | rag-retrieval
language::      en | da | de
status::        ingested | reviewed | needs-update | superseded
```
"""
TEMPLATES = """## Templates
- ## Research Paper
template:: Research Paper
	- # <Title>
		- ## Abstract
		- ## Key Points
		- ## Relevance to This Project
		- ## Related Pages
		- ## Verification
		- ## Highlights
		- ## Local PDF
- ### Research Paper — page-property block
\t- ```
\t  topic:: rag-foundations | rag-retrieval
\t  ```
"""

PAPER_PROPS = {
    "source-type": "paper",
    "document-id": "arXiv:2005.11401",
    "topic": "rag-foundations",
    "language": "en",
    "status": "ingested",
    "date": "2026-09-01",
    "url": "https://arxiv.org/abs/2005.11401",
    "trustworthiness": "HIGH",
    "pdf-path": "../assets/papers/RAG-Lewis2020-2005.11401.pdf",
}


RAG_PAPER = dict(
    title="Retrieval-Augmented Generation",
    authors=["Patrick Lewis", "Ethan Perez"],
    year=2020,
    abstract="An abstract.",
    venue="NeurIPS",
    arxiv_id="2005.11401",
    s2_id="p1",
    citations=5000,
)


def fake_lookup(warnings=(), **fields):
    """A stand-in for core.lookup that knows one paper: the RAG paper unless `fields` override it."""
    found = Lookup(
        Paper(**RAG_PAPER | fields), {"semantic_scholar": "found", "openalex": "found"}, list(warnings)
    )
    return lambda identifier: found


def no_lookup(identifier):
    raise AssertionError(f"looked up {identifier}, but bad input must cost no network call")


def ingest_args(**kw):
    """Keyword arguments for prepare_ingest: one valid paper, overridable."""
    base = dict(
        identifier="2005.11401",
        paper_id="RAG-Lewis2020",
        topic="rag-retrieval",
        verdict="HIGH",
        verdict_reasoning="NeurIPS",
        key_points=["k"],
        relevance="r",
        related_pages=["Concepts/RAG"],
        lookup=fake_lookup(),
        today=date(2026, 1, 2),
    )
    return base | kw


def paper_page(props=None, body=None, drop=()):
    merged = {k: v for k, v in (PAPER_PROPS | (props or {})).items() if k not in drop}
    head = "\n".join(f"{k}:: {v}" for k, v in merged.items())
    body = body if body is not None else "- # RAG\n\t- ## Related Pages\n\t\t- [[Concepts/RAG]]\n"
    return f"{head}\n\n{body}"


def page_file(root, title):
    return root / "pages" / f"{title.replace('/', '%2F')}.md"


def _known_to_logseq(root, title):
    """Logseq has a page if it has a file or if any page links to it."""
    link = f"[[{title}]]".lower()
    return page_file(root, title).exists() or any(
        link in p.read_text().lower() for p in (root / "pages").glob("*.md")
    )


def apply_calls(root, calls):
    """Apply the tools' `calls` to a tmp brain the way mcp-logseq would.

    A stand-in for mcp-logseq. `create_page` writes `key:: value` property lines, a blank line and the
    content to the encoded file; `update_page` with mode "append" appends to it, creating the file if
    needed (e.g. `Log`); with mode "replace" it rewrites the page, properties first.

    Checked live against mcp-logseq 1.10.0 and Logseq 0.10.15 (2026-11-13): a page that another page
    links to exists in Logseq without a file, so `create_page` refuses it, while `update_page` refuses a
    page Logseq does not have at all. The stand-in refuses both the same way.
    """
    for call in calls:
        args = call["arguments"]
        match call["tool"], args.get("mode"):
            case "create_page", None:
                path = page_file(root, args["title"])
                assert not _known_to_logseq(root, args["title"]), (
                    f"create_page on a page Logseq has: {args['title']}"
                )
                props = "".join(f"{k}:: {v}\n" for k, v in args["properties"].items())
                path.write_text(f"{props}\n{args['content']}\n")
            case "update_page", "replace":
                path = page_file(root, args["page_name"])
                assert _known_to_logseq(root, args["page_name"]), (
                    f"update_page on a missing page: {args['page_name']}"
                )
                props = "".join(f"{k}:: {v}\n" for k, v in args.get("properties", {}).items())
                path.write_text(f"{props}\n{args['content']}\n")
            case "update_page", "append":
                path = page_file(root, args["page_name"])
                old = path.read_text() if path.exists() else ""
                path.write_text(
                    old + ("" if old.endswith("\n") or not old else "\n") + args["content"] + "\n"
                )
            case _:
                raise AssertionError(
                    f"mcp-logseq stand-in does not support {call['tool']} {args.get('mode')}"
                )


def write_pdf(path, pages, size=(612, 792)):
    """A text PDF: `pages` is a list of pages, each a list of (x, baseline_y, text) lines in PDF points."""
    c = canvas.Canvas(str(path), pagesize=size)
    for lines in pages:
        c.setFont("Helvetica", 12)
        for x, y, text in lines:
            c.drawString(x, y, text)
        c.showPage()
    c.save()


@pytest.fixture(autouse=True)
def fresh_lookup_memo():
    core._memo.clear()


@pytest.fixture
def make_brain(tmp_path):
    """build(pages={title: text}, assets=[filenames]) -> brain root."""

    def build(pages=None, assets=(), agents=AGENTS, templates=TEMPLATES, config_edn=None, raw_files=None):
        (tmp_path / "pages").mkdir(exist_ok=True)
        (tmp_path / "assets" / "papers").mkdir(parents=True, exist_ok=True)
        (tmp_path / "AGENTS.md").write_text(agents)
        (tmp_path / "pages" / "Templates.md").write_text(templates)
        for title, text in (pages or {}).items():
            page_file(tmp_path, title).write_text(text)
        for filename, text in (raw_files or {}).items():
            (tmp_path / "pages" / filename).write_text(text)
        if config_edn is not None:
            (tmp_path / "logseq").mkdir(exist_ok=True)
            (tmp_path / "logseq" / "config.edn").write_text(config_edn)
        for name in assets:
            (tmp_path / "assets" / "papers" / name).write_bytes(b"%PDF-1")
        return tmp_path

    return build


@pytest.fixture
def healthy_brain(make_brain):
    """One well-formed paper that is linked from a concept page."""
    return make_brain(
        pages={
            "Sources/Research/RAG-Lewis2020": paper_page(),
            "Concepts/RAG": "- see [[Sources/Research/RAG-Lewis2020]]\n",
        },
        assets=["RAG-Lewis2020-2005.11401.pdf"],
    )
