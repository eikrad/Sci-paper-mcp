"""What the running Logseq app says about itself, over its HTTP API (read-only)."""

from pathlib import Path

import httpx

from . import config
from .brain import SchemaError


def verify_open_graph(root: Path) -> str | None:
    """Ask Logseq which graph is open (read-only). Raises on a mismatch, returns a warning if unsure.

    mcp-logseq writes into whatever graph Logseq has open, independent of SECOND_BRAIN_PATH.
    """
    token = config.logseq_api_token()
    if not token:
        return "could not verify the open Logseq graph: LOGSEQ_API_TOKEN is not set"
    try:
        r = httpx.post(
            f"{config.logseq_api_url()}/api",
            headers={"Authorization": f"Bearer {token}"},
            json={"method": "logseq.App.getCurrentGraph", "args": []},
            timeout=10,
        )
        r.raise_for_status()
        graph = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return f"could not verify the open Logseq graph: {e}"
    if not graph or not graph.get("path"):
        raise SchemaError("no graph is open in Logseq; open the brain before applying the calls")
    if Path(graph["path"]).resolve() != root.resolve():
        raise SchemaError(
            f"wrong graph: Logseq has {graph['path']} open but SECOND_BRAIN_PATH is {root}. "
            "Open the right graph in Logseq, or the pages would land in the wrong brain."
        )
    return None
