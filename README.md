# sci-paper-mcp

MCP server that finds research papers on arXiv and Semantic Scholar, checks how trustworthy they are
(venue, citations, authors, retractions via OpenAlex), fetches the open-access PDF and prepares a
structured page for your Logseq second brain. Runs locally over stdio and works with Claude Code,
Cursor, Codex, opencode and any other MCP-capable agent.

Design decisions: [docs/adr](docs/adr). Vocabulary: [GLOSSARY.md](GLOSSARY.md).

## Tools

| Tool | What it does |
|---|---|
| `search_papers` | arXiv, Semantic Scholar and OpenAlex, merged and de-duplicated (richer sources fill gaps); `warnings` lists failed sources |
| `trust_check` | Proposes HIGH/MEDIUM/LOW with reasons; merges Semantic Scholar and OpenAlex |
| `fetch_pdf` | Saves `assets/papers/<PAPER-ID>-<id>.pdf`, never overwrites |
| `prepare_ingest` | Validates against the brain's `AGENTS.md`, returns `create_page`/`update_page` calls for `mcp-logseq`. Writes nothing |
| `lint` | Read-only health check of the brain |

Pages are written by the agent through `mcp-logseq`; this server only reads the graph and writes PDFs.

## Configuration (environment)

| Variable | Purpose |
|---|---|
| `SECOND_BRAIN_PATH` | Logseq graph to read rules from / write PDFs into |
| `UNPAYWALL_EMAIL` | Contact address for Unpaywall lookups |
| `LOGSEQ_API_URL`, `LOGSEQ_API_TOKEN` | Same values as for `mcp-logseq`. `prepare_ingest` asks Logseq (read-only) which graph is open and refuses if it is not `SECOND_BRAIN_PATH` |
| `S2_API_KEY`, `OPENALEX_API_KEY` | Optional; raise rate limits. Each key is sent only to its own service |

## Use

```bash
uv run sci-paper-mcp serve                      # MCP over stdio
uv run sci-paper-mcp search "retrieval augmented generation"
uv run sci-paper-mcp lint --brain ~/projects/second-brain   # exit 1 on errors (--fail-on warning|todo|never)
```

## Development

Test-driven; tests sit at the public seams (core functions with HTTP mocked, fixture brains, the MCP
surface, the CLI). Live-API tests are marked `live` and excluded from CI.

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pytest            # add -m live to hit the real APIs
```

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs ruff and pytest. To lint your graph in its own
repo's CI, copy [examples/second-brain-lint.yml](examples/second-brain-lint.yml).
