"""CLI over the core functions: sci-paper-mcp {search,trust,pdf,serve}."""

import argparse
import json
import sys

import httpx

from . import core


def main(argv: list[str] | None = None) -> None:
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
    sub.add_parser("serve", help="run the MCP server over stdio")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        from .server import mcp

        mcp.run()
        return
    try:
        result = {
            "search": lambda: core.search_papers(a.query, a.limit),
            "trust": lambda: core.trust_check(a.identifier),
            "pdf": lambda: core.fetch_pdf(a.identifier, a.paper_id, a.dest),
        }[a.cmd]()
    except (RuntimeError, httpx.HTTPError) as e:
        sys.exit(f"error: {e}")
    print(json.dumps(result, indent=2, ensure_ascii=False))
