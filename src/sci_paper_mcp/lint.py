"""Read-only, mechanical health check of a brain (AGENTS.md "Lint workflow").

Judgement calls (contradictions, concept gaps) stay with the agent; this only reports facts.
"""

import re
from datetime import date
from pathlib import Path

from .schema import load_schema

REQUIRED = (
    "source-type", "document-id", "topic", "language", "status", "date", "url",
    "trustworthiness", "pdf-path",
)  # fmt: skip
RESEARCH = "Sources/Research/"
STALE_DAYS = 60


def _title(path: Path) -> str:
    return path.stem.replace("%2F", "/").replace("___", "/")


def _pages(root: Path) -> dict[str, str]:
    return {_title(p): p.read_text() for p in sorted((root / "pages").glob("*.md"))}


_TERM = r"\(page-property\s+([^\s()]+)\s+([^\s()]+)\)"


def _index_queries(index: str) -> tuple[list[dict[str, str]], list[str]]:
    """Understood queries as {property: value} conjunctions, plus the queries we cannot evaluate."""
    understood, unknown = [], []
    for body in re.findall(r"\{\{query\s+(.+?)\}\}", index):
        body = body.strip()
        if re.fullmatch(_TERM, body) or re.fullmatch(rf"\(and(\s+{_TERM})+\s*\)", body):
            understood.append(dict(re.findall(_TERM, body)))
        else:
            unknown.append(body)
    return understood, unknown


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _related(text: str) -> list[str]:
    """`[[links]]` inside the '## Related Pages' section."""
    m = re.search(r"##\s+Related Pages\s*\n(.*?)(?=\n\s*(?:-\s+)?##\s|\Z)", text, re.S)
    return re.findall(r"\[\[([^\]]+)\]\]", m[1]) if m else []


def _properties(text: str) -> dict[str, str]:
    """Page properties: `key:: value` lines before the first block."""
    props = {}
    for line in text.splitlines():
        if line.startswith(("-", "\t", " ")):
            break
        if m := re.match(r"^([\w-]+)::\s*(.*)$", line):
            props[m[1]] = m[2].strip()
    return props


def lint(root: Path | None, today: date | None = None) -> dict:
    today = today or date.today()
    schema = load_schema(root)
    pages = _pages(schema.root)
    findings: list[dict] = []

    def add(check: str, page: str, message: str, severity: str = "error") -> None:
        findings.append({"check": check, "severity": severity, "page": page, "message": message})

    if m := re.search(r"^\s*topic::\s+(.+)$", pages.get("Templates", ""), re.M):
        in_templates = {v.strip() for v in m[1].split("|")}
        missing = sorted(set(schema.taxonomy) - in_templates)
        if missing:
            add("drift", "Templates", f"Templates topic list lacks AGENTS.md topics: {', '.join(missing)}")
        extra = sorted(in_templates - set(schema.taxonomy))
        if extra:
            add("drift", "Templates", f"Templates topic list has topics not in AGENTS.md: {', '.join(extra)}")
    index_queries, unknown_queries = _index_queries(pages.get("Index", ""))
    for q in unknown_queries:
        add("index", "Index", f"query not understood, coverage not checked for it: {q}", "todo")
    known = {t.lower() for t in pages}
    for title, text in pages.items():
        if not title.startswith(RESEARCH):
            continue
        props = _properties(text)
        missing = [k for k in REQUIRED if k not in props]
        if missing:
            add("schema", title, f"missing required properties: {', '.join(missing)}")
        for prop in ("source-type", "topic", "language", "status"):
            value = props.get(prop)
            if value is not None and value not in schema.values[prop]:
                where = "taxonomy" if prop == "topic" else "allowed values"
                add("schema", title, f"{prop} '{value}' is not in the {where} {schema.values[prop]}")
        linked_from = [
            t for t, other in pages.items() if t != title and f"[[{title}]]".lower() in other.lower()
        ]
        if not linked_from:
            add("links", title, "no backlinks: no other page links here", "warning")
        for target in _related(text):
            if target.lower() not in known:
                add("links", title, f"Related Pages links to a page that does not exist: {target}")
        for hls in re.findall(r"\{\{embed \[\[(hls__[^\]]+)\]\]\}\}", text):
            if "ls-type:: annotation" not in pages.get(hls, ""):
                add("highlights", title, f"no highlights yet on {hls} (PDF not annotated)", "todo")
        if props.get("status") == "needs-update" and (d := _parse_date(props.get("date"))):
            age = (today - d).days
            if age > STALE_DAYS:
                add("stale", title, f"status needs-update for {age} days (limit {STALE_DAYS})", "warning")
        if index_queries and not any(all(props.get(k) == v for k, v in q.items()) for q in index_queries):
            add(
                "index",
                title,
                f"matched by no Index query (source-type '{props.get('source-type')}', "
                f"topic '{props.get('topic')}'); check both properties",
            )
        pdf = props.get("pdf-path")
        if pdf and pdf != "not-found" and not (schema.root / "pages" / pdf).resolve().exists():
            add("pdf", title, f"pdf-path points to a missing file: {pdf}")
        if re.search(r"^[\s-]*[\w-]+:::", text, re.M):
            add("schema", title, "property uses ':::' (invalid Logseq syntax, use '::')")
    summary: dict[str, int] = {}
    for f in findings:
        summary[f["check"]] = summary.get(f["check"], 0) + 1
    return {"findings": findings, "summary": summary}
