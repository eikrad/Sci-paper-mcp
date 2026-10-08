"""CLI over the core functions: sci-paper-mcp {search,trust,pdf,lint,serve}."""

import argparse
import json
import sys
from pathlib import Path

import httpx

from . import config, core
from .lint import lint

SEVERITY_RANK = {"todo": 0, "warning": 1, "error": 2}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sci-paper-mcp")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("-n", "--limit", type=int, default=10)
    t = sub.add_parser("trust")
    t.add_argument("identifier", help="DOI, arXiv id, or Semantic Scholar id")
    f = sub.add_parser("pdf")
    f.add_argument("identifier")
    f.add_argument("-p", "--paper-id")
    f.add_argument("-d", "--dest")
    li = sub.add_parser("lint", help="read-only health check of the brain; exit 1 on findings")
    li.add_argument("--brain", help="path to the brain (default: $SECOND_BRAIN_PATH)")
    li.add_argument("--fail-on", choices=["error", "warning", "todo", "never"], default="error")
    sub.add_parser("serve", help="run the MCP server over stdio")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        from .server import mcp

        mcp.run()
        return 0
    try:
        result = {
            "search": lambda: core.search_papers(a.query, a.limit),
            "trust": lambda: core.trust_check(a.identifier),
            "pdf": lambda: core.fetch_pdf(a.identifier, a.paper_id, a.dest),
            "lint": lambda: lint(Path(a.brain).expanduser() if a.brain else config.second_brain_path()),
        }[a.cmd]()
    except (RuntimeError, httpx.HTTPError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if a.cmd == "lint" and a.fail_on != "never":
        threshold = SEVERITY_RANK[a.fail_on]
        if any(SEVERITY_RANK[f["severity"]] >= threshold for f in result["findings"]):
            return 1
    return 0
