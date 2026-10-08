"""Shared fixture: build a throwaway Logseq brain on disk."""

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
		- ## Related Pages
		- ## Highlights
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


def paper_page(props=None, body=None, drop=()):
    merged = {k: v for k, v in (PAPER_PROPS | (props or {})).items() if k not in drop}
    head = "\n".join(f"{k}:: {v}" for k, v in merged.items())
    body = body if body is not None else "- # RAG\n\t- ## Related Pages\n\t\t- [[Concepts/RAG]]\n"
    return f"{head}\n\n{body}"


@pytest.fixture
def make_brain(tmp_path):
    """build(pages={title: text}, assets=[filenames]) -> brain root."""

    def build(pages=None, assets=(), agents=AGENTS, templates=TEMPLATES):
        (tmp_path / "pages").mkdir(exist_ok=True)
        (tmp_path / "assets" / "papers").mkdir(parents=True, exist_ok=True)
        (tmp_path / "AGENTS.md").write_text(agents)
        (tmp_path / "pages" / "Templates.md").write_text(templates)
        for title, text in (pages or {}).items():
            (tmp_path / "pages" / f"{title.replace('/', '%2F')}.md").write_text(text)
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
