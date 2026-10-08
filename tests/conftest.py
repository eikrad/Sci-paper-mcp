"""Shared fixtures: build a throwaway Logseq brain on disk."""

from datetime import date

import pytest

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


def ingest_args(**kw):
    """Keyword arguments for prepare_ingest: one valid paper, overridable."""
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


def paper_page(props=None, body=None, drop=()):
    merged = {k: v for k, v in (PAPER_PROPS | (props or {})).items() if k not in drop}
    head = "\n".join(f"{k}:: {v}" for k, v in merged.items())
    body = body if body is not None else "- # RAG\n\t- ## Related Pages\n\t\t- [[Concepts/RAG]]\n"
    return f"{head}\n\n{body}"


def page_file(root, title):
    return root / "pages" / f"{title.replace('/', '%2F')}.md"


def apply_calls(root, calls):
    """Apply prepare_ingest's `calls` to a tmp brain the way mcp-logseq would.

    A stand-in for mcp-logseq, not verified against a live Logseq (ADR 0006). `create_page` writes
    `key:: value` property lines, a blank line and the content to the encoded file; `update_page`
    with mode "append" appends to it, creating the file if needed (e.g. `Log`).
    """
    for call in calls:
        args = call["arguments"]
        match call["tool"], args.get("mode"):
            case "create_page", None:
                path = page_file(root, args["title"])
                assert not path.exists(), f"create_page on an existing page: {args['title']}"
                props = "".join(f"{k}:: {v}\n" for k, v in args["properties"].items())
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


@pytest.fixture
def make_brain(tmp_path):
    """build(pages={title: text}, assets=[filenames]) -> brain root."""

    def build(pages=None, assets=(), agents=AGENTS, templates=TEMPLATES):
        (tmp_path / "pages").mkdir(exist_ok=True)
        (tmp_path / "assets" / "papers").mkdir(parents=True, exist_ok=True)
        (tmp_path / "AGENTS.md").write_text(agents)
        (tmp_path / "pages" / "Templates.md").write_text(templates)
        for title, text in (pages or {}).items():
            page_file(tmp_path, title).write_text(text)
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
