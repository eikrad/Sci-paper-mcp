"""Read the rules of a brain from its own files (ADR 0003)."""

import re
from dataclasses import dataclass
from pathlib import Path


class SchemaError(RuntimeError):
    pass


@dataclass
class Schema:
    root: Path
    values: dict[str, list[str]]  # property -> allowed values, e.g. "topic"
    sections: list[str]  # Research Paper template headings, in order

    @property
    def taxonomy(self) -> list[str]:
        return self.values["topic"]


def page_file_candidates(root: Path, title: str) -> list[Path]:
    pages = root / "pages"
    return [pages / f"{title.replace('/', sep)}.md" for sep in ("%2F", "___")]


def page_exists(root: Path, title: str) -> bool:
    return any(p.exists() for p in page_file_candidates(root, title))


def read_page(root: Path, title: str) -> str | None:
    return next((p.read_text() for p in page_file_candidates(root, title) if p.exists()), None)


def _property_values(agents: str, prop: str) -> list[str]:
    m = re.search(rf"^{re.escape(prop)}::\s+(.+)$", agents, re.M)
    if not m:
        raise SchemaError(f"AGENTS.md has no '{prop}::' line in its property block")
    values = [v.strip() for v in m.group(1).split("|")]
    return [re.split(r"\s{2,}|\s\(", v)[0] for v in values if v]


def load_schema(root: Path | None) -> Schema:
    if root is None:
        raise SchemaError("SECOND_BRAIN_PATH is not set")
    agents_file = root / "AGENTS.md"
    if not agents_file.exists():
        raise SchemaError(f"{agents_file} not found; this brain has no schema (ADR 0003)")
    agents = agents_file.read_text()
    values = {p: _property_values(agents, p) for p in ("source-type", "topic", "language", "status")}

    templates = read_page(root, "Templates")
    if templates is None:
        raise SchemaError(f"{root}/pages/Templates.md not found")
    start = templates.find("## Research Paper")
    end = templates.find("page-property block", start)
    if start < 0 or end < 0:
        raise SchemaError("Templates has no 'Research Paper' template")
    headings = re.findall(r"^\s*-\s+##\s+(.+?)\s*$", templates[start:end], re.M)
    if not headings:
        raise SchemaError("Research Paper template has no '##' sections")
    return Schema(root, values, headings)
