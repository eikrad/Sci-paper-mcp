# Glossary

- **Brain** — a Logseq graph on disk (e.g. `second-brain`), located via `SECOND_BRAIN_PATH`. Its `AGENTS.md` is the schema; this server applies it and never owns it.
- **Paper** — a research paper identified by DOI, arXiv id or Semantic Scholar id.
- **Verdict** — `HIGH | MEDIUM | LOW`, the trustworthiness of a paper as defined in the brain's `AGENTS.md`. The server proposes it with `reasons`; the agent may override it.
- **Raw layer** — `assets/papers/` in the brain. Immutable: PDFs are added, never modified or overwritten.
- **Wiki layer** — `pages/` in the brain. Written by the agent through `mcp-logseq`, never by this server.
- **PAPER-ID** — page and PDF stem such as `RAG-Lewis2020`. The agent may supply it; otherwise the server derives `<FirstAuthor><Year>`.
- **Ingest** — turning a paper into a brain page: trust check, PDF, page, backlinks, log entry. This server only prepares it (`prepare_ingest`).
- **Lint** — read-only, mechanical health check of the brain. Judgement calls (contradictions, concept gaps) stay with the agent.
