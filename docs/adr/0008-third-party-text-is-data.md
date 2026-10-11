# 0008 — Titles and abstracts are third-party text: scrubbed and flagged, never blocked

Status: accepted.

Titles and abstracts come from arXiv, Semantic Scholar and OpenAlex, which index whatever authors submit. They go into the agent's context and, through `prepare_ingest`, into the graph, where every later agent reads them again via `mcp-logseq`. That is the indirect prompt injection path (Hou et al. 2025), and agents do not reliably separate data from instructions (Guo et al. 2025).

`search_papers`, `trust_check` and `prepare_ingest` therefore pass titles and abstracts through `untrusted.scrub`:

- Invisible characters are removed: zero-width and bidi controls, word joiners, BOM, and the Unicode tag block, which can spell out ASCII that no reader sees. Removing them never changes what a person reads, so this is safe to do always. A warning names the field.
- Text that addresses the reader, such as "ignore previous instructions", "do not tell the user", `<IMPORTANT>` tags, "you must call the … tool" or "read ~/.ssh/…", is flagged with a warning and left as it is.

Flagging, not blocking: the patterns are a cheap first filter, like Stage I of MCP-Guard (Xing et al. 2025: 97.7% precision but 38.9% recall). A paraphrase passes, so blocking would suggest a protection the filter does not give. Papers about prompt injection may also quote such phrases. The patterns are kept narrow so that an abstract that only *discusses* these attacks raises nothing; a test pins that. The agent, and the person approving its calls, decide.

Not covered: the full text of PDFs, which the agent reads itself, and the agent's own fields in `prepare_ingest` apart from an `abstract` override.
