# 0002 — Pages are written by the agent through mcp-logseq

Status: accepted. Supersedes the handover decision to write page files directly.

Logseq is open locally anyway (`mcp-logseq` needs it), so direct file writes risk conflicts with the running app. `prepare_ingest` therefore returns page text, backlink appends and the log entry; the agent applies them with `create_page` / `update_page`. Cloud operation is dropped. Only PDFs are written as files by this server, since `mcp-logseq` has no binary/asset tool. Reading the graph (`lint`) is by file and conflict-free.
