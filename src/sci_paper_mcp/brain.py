"""The Brain: a Logseq graph on disk, the rules it carries (ADR 0003) and the paper-page format.

Every convention about how the graph is laid out lives here, so that `prepare_ingest` (which renders
paper pages), `lint` (which checks them) and `fetch_pdf` (which writes PDFs) cannot drift apart.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path, PurePosixPath
from typing import TypeGuard


class SchemaError(RuntimeError):
    pass


@dataclass
class Schema:
    values: dict[str, list[str]]  # property -> allowed values, e.g. "topic"
    sections: list[str]  # Research Paper template headings, in order
    template_topics: list[str] | None  # the `topic::` line of Templates, None if it has none

    @property
    def taxonomy(self) -> list[str]:
        return self.values["topic"]


# --- the paper-page format -------------------------------------------------------------------------

_RESEARCH = "Sources/Research/"
_NOT_FOUND = "not-found"  # pdf-path of a paper whose PDF is not in the raw layer
_HIGHLIGHTS = "hls__"
_EMBED = re.compile(r"\{\{embed \[\[(" + re.escape(_HIGHLIGHTS) + r"[^\]]+)\]\]\}\}")


def paper_title(paper_id: str) -> str:
    return f"{_RESEARCH}{paper_id}"


def is_paper_title(title: str) -> bool:
    return title.startswith(_RESEARCH)


def names_pdf(pdf_path: str | None) -> TypeGuard[str]:
    """Whether a pdf-path property value names a PDF (absent or 'not-found' means there is none)."""
    return bool(pdf_path) and pdf_path != _NOT_FOUND


def pdf_stem(pdf: str) -> str:
    """The stem of a pdf-path property value or of a PDF file name."""
    return PurePosixPath(pdf).stem


def paper_properties(
    *,
    arxiv_id: str | None,
    doi: str | None,
    topic: str,
    language: str,
    verdict: str,
    date: str,
    pdf_path: str | None,
) -> dict[str, str]:
    """The property block of a new paper page."""
    return {
        "source-type": "paper",
        "document-id": f"arXiv:{arxiv_id}" if arxiv_id else f"doi:{doi}",
        "topic": topic,
        "language": language,
        "status": "ingested",
        "date": date,
        "url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else f"https://doi.org/{doi}",
        "trustworthiness": verdict,
        "pdf-path": pdf_path if names_pdf(pdf_path) else _NOT_FOUND,
    }


# What lint demands of a paper page is what prepare_ingest writes.
REQUIRED_PROPERTIES = tuple(
    paper_properties(arxiv_id="", doi="", topic="", language="", verdict="", date="", pdf_path=None)
)


def parse_properties(text: str) -> dict[str, str]:
    """Page properties: `key:: value` lines before the first block."""
    props = {}
    for line in text.splitlines():
        if line.startswith(("-", "\t", " ")):
            break
        if m := re.match(r"^([\w-]+)::\s*(.*)$", line):
            props[m[1]] = m[2].strip()
    return props


def highlights_embed(pdf: str) -> str:
    """The block that embeds the highlights page Logseq keeps for a PDF (a pdf-path value or file name)."""
    return f"{{{{embed [[{_HIGHLIGHTS}{pdf_stem(pdf)}]]}}}}"


def embedded_highlights(text: str) -> list[str]:
    """Titles of the highlights pages that a paper page embeds."""
    return _EMBED.findall(text)


def _safe(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in text)


def resolve_paper_id(paper_id: str | None, authors: list[str], year: int | None) -> str:
    """The agent's PAPER-ID made file-safe, else `<FirstAuthor><Year>`."""
    if paper_id:
        return _safe(paper_id)
    if not authors or not year:
        raise RuntimeError("Cannot derive a PAPER-ID (author/year unknown); pass paper_id.")
    return f"{_safe(authors[0].split()[-1])}{year}"


def pdf_name(
    paper_id: str, *, arxiv_id: str | None = None, doi: str | None = None, s2_id: str | None = None
) -> str:
    """`<PAPER-ID>-<id>.pdf`, the one name of a paper's PDF, whether it exists yet or not."""
    return f"{_safe(paper_id)}-{_safe(arxiv_id or doi or s2_id or 'unknown')}.pdf"


# --- the raw layer ---------------------------------------------------------------------------------

_RAW = "assets/papers"


def _taken(path: Path) -> RuntimeError:
    return RuntimeError(f"{path} already exists; the raw layer is never overwritten.")


def save_pdf(folder: Path, name: str, download: Callable[[], bytes]) -> Path:
    """Add a PDF to the raw layer, or to any other download folder; never overwrites.

    Refuses before calling `download` when the file exists.
    """
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    if path.exists():
        raise _taken(path)
    content = download()
    try:
        with path.open("xb") as f:
            f.write(content)
    except FileExistsError:
        raise _taken(path) from None
    return path


# --- the graph -------------------------------------------------------------------------------------

_SEPARATORS = ("%2F", "___")  # how a file name encodes the `/` of a page title


def _title(path: Path) -> str:
    title = path.stem
    for sep in _SEPARATORS:
        title = title.replace(sep, "/")
    return title


def _property_values(agents: str, prop: str) -> list[str]:
    m = re.search(rf"^{re.escape(prop)}::\s+(.+)$", agents, re.M)
    if not m:
        raise SchemaError(f"AGENTS.md has no '{prop}::' line in its property block")
    values = [v.strip() for v in m.group(1).split("|")]
    return [re.split(r"\s{2,}|\s\(", v)[0] for v in values if v]


class Brain:
    """A Logseq graph on disk. Cheap to build; reads the graph only when asked.

    The schema loads lazily, so a graph without an AGENTS.md can still take PDFs.
    """

    def __init__(self, root: Path | None):
        if root is None:
            raise SchemaError("SECOND_BRAIN_PATH is not set")
        self.root = root

    @cached_property
    def schema(self) -> Schema:
        agents_file = self.root / "AGENTS.md"
        if not agents_file.exists():
            raise SchemaError(f"{agents_file} not found; this brain has no schema (ADR 0003)")
        agents = agents_file.read_text()
        values = {p: _property_values(agents, p) for p in ("source-type", "topic", "language", "status")}

        templates = self.page("Templates")
        if templates is None:
            raise SchemaError(f"{self.root}/pages/Templates.md not found")
        start = templates.find("## Research Paper")
        end = templates.find("page-property block", start)
        if start < 0 or end < 0:
            raise SchemaError("Templates has no 'Research Paper' template")
        headings = re.findall(r"^\s*-\s+##\s+(.+?)\s*$", templates[start:end], re.M)
        if not headings:
            raise SchemaError("Research Paper template has no '##' sections")
        topics = re.search(r"^\s*topic::\s+(.+)$", templates, re.M)
        return Schema(values, headings, [v.strip() for v in topics[1].split("|")] if topics else None)

    def pages(self) -> dict[str, str]:
        """Every page's text by title, in file-name order."""
        return {_title(p): p.read_text() for p in sorted((self.root / "pages").glob("*.md"))}

    def _file(self, title: str) -> Path | None:
        files = (self.root / "pages" / f"{title.replace('/', sep)}.md" for sep in _SEPARATORS)
        return next((f for f in files if f.exists()), None)

    def page(self, title: str) -> str | None:
        file = self._file(title)
        return file.read_text() if file else None

    def has_page(self, title: str) -> bool:
        return self._file(title) is not None

    @property
    def raw_layer(self) -> Path:
        return self.root / _RAW

    def pdf_path(self, name: str) -> str:
        """The pdf-path property value for a PDF in the raw layer: relative to `pages/`."""
        return f"../{_RAW}/{name}"

    def has_pdf(self, pdf_path: str) -> bool:
        """Whether a pdf-path property value points at an existing file."""
        return (self.root / "pages" / pdf_path).resolve().exists()

    def find_pdf(
        self, paper_id: str, *, arxiv_id: str | None = None, doi: str | None = None, s2_id: str | None = None
    ) -> str | None:
        """The pdf-path property value of a paper's PDF in the raw layer, else None.

        Looks for `pdf_name(paper_id, ...)` under each of the ids (arXiv id first), case-insensitively:
        which id names the file depends on which source answered when it was saved, and OpenAlex
        lowercases DOIs. Only exact names count, so paper id `RAG` never finds `RAG-Lewis2020-….pdf`.
        """
        if not self.raw_layer.is_dir():
            return None
        present = {f.name.lower(): f.name for f in self.raw_layer.iterdir()}
        ids = (("arxiv_id", arxiv_id), ("doi", doi), ("s2_id", s2_id))
        for name in (pdf_name(paper_id, **{kind: value}) for kind, value in ids if value):
            if found := present.get(name.lower()):
                return self.pdf_path(found)
        return None
