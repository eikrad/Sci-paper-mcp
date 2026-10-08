# 0006 — prepare_ingest verifies which graph Logseq has open

Status: accepted. Follows 0002.

`mcp-logseq` writes into whichever graph the Logseq desktop app has open, independent of `SECOND_BRAIN_PATH`. With several brains (second-brain, radiation-brain) pages could silently land in the wrong one. `prepare_ingest` therefore asks Logseq (`logseq.App.getCurrentGraph` over the HTTP API, read-only) and refuses to return any calls on a mismatch or when no graph is open. If Logseq cannot be reached or no token is set it only warns, so the tool stays usable; `verify_graph=False` skips the check in code.

Not yet verified against a live Logseq: the request shape follows Logseq's plugin API (`getCurrentGraph` returns name and path) and is tested against mocked responses only.
