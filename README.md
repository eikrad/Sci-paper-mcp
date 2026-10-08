# sci-paper-mcp

[![CI](https://github.com/eikrad/Sci-paper-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/eikrad/Sci-paper-mcp/actions/workflows/ci.yml)

MCP server that finds research papers on arXiv, Semantic Scholar and OpenAlex, checks how trustworthy
they are (venue, citations, authors, retractions), fetches the open-access PDF and prepares a
structured page for your Logseq second brain. Runs locally over stdio and works with Claude Code,
Cursor, Codex, opencode and any other MCP-capable agent.

Design decisions: [docs/adr](docs/adr). Vocabulary: [GLOSSARY.md](GLOSSARY.md).

## Install

Needs [uv](https://docs.astral.sh/uv/). Nothing to install separately: point your agent at a release tag and `uv` fetches it.

```json
{
  "mcpServers": {
    "sci-paper-mcp": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/eikrad/Sci-paper-mcp@v0.1.0", "sci-paper-mcp", "serve"],
      "env": {
        "SECOND_BRAIN_PATH": "/path/to/your/logseq-graph",
        "LOGSEQ_API_URL": "http://localhost:12315",
        "LOGSEQ_API_TOKEN": "<token from Logseq: Settings → Features → HTTP APIs server>"
      }
    }
  }
}
```

Pages are written with [`mcp-logseq`](https://github.com/ergut/mcp-logseq), which this server is meant to run next to
(`uv run --no-project --with mcp-logseq==1.10.0 mcp-logseq`; the old `mcp<2` pin is no longer needed since 1.9.0).
Pin the version, as the tag above does for this server: an MCP server's tool descriptions go straight into the
agent's context, so an update should be a decision, not a side effect of a restart. 1.10.0 is the version
verified live (see v0.1.0 below).

## Tools

| Tool | What it does |
|---|---|
| `search_papers` | arXiv, Semantic Scholar and OpenAlex, merged and de-duplicated (richer sources fill gaps); `warnings` lists failed sources |
| `trust_check` | Proposes HIGH/MEDIUM/LOW with reasons; merges Semantic Scholar and OpenAlex |
| `fetch_pdf` | Saves `assets/papers/<PAPER-ID>-<id>.pdf`, never overwrites. PDF from arXiv, Semantic Scholar, OpenAlex or Unpaywall |
| `prepare_ingest` | Takes the paper's identifier plus your judgement (topic, verdict, key points, relevance, related pages), looks up the metadata and finds the PDF in `assets/papers/` itself, validates against the brain's `AGENTS.md` and returns `create_page`/`update_page` calls for `mcp-logseq`. Writes nothing |
| `lint` | Read-only health check of the brain |

Pages are written by the agent through `mcp-logseq`; this server only reads the graph and writes PDFs.

A typical ingest: `trust_check` → `fetch_pdf` → `prepare_ingest` with the same identifier (and the same
`paper_id`, if you choose one) → apply the returned `calls` with `mcp-logseq`. The paper is looked up once
per server run and shared by all three tools.

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

Test-driven; tests sit at the public seams: core functions with HTTP mocked, the verdict rules as a pure
function, fixture brains (including an ingest-then-lint round trip), the MCP surface and the CLI. Live-API tests are marked `live` and excluded from CI.

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pytest            # add -m live to hit the real APIs
```

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs ruff and pytest. To lint your graph in its own
repo's CI, copy [examples/second-brain-lint.yml](examples/second-brain-lint.yml).

Branches: feature → `staging` → `main`. PRs into `main` come only from `staging`, and every commit needs a
Conventional Commit prefix (`feat:`, `fix:`, `refactor:`, `docs:`, …); CI checks both.
Releases are cut by release-please from those prefixes; see [docs/releasing.md](docs/releasing.md).

## Releases

### Unreleased

**Breaking:** `prepare_ingest` takes the paper's `identifier` (DOI, arXiv id or S2 id) instead of copied metadata. The server
looks up title, authors, venue, year, citations, ids, the Semantic Scholar link and peer-review status itself and finds the
PDF in `assets/papers/` (run `fetch_pdf` first). Removed: `title`, `authors`, `arxiv_id`, `doi`, `venue`, `year`, `citations`,
`peer_reviewed`, `semantic_scholar_url`, `pdf_path`; `abstract` is now an optional override and `paper_id` is optional (derived
like `fetch_pdf` does). The page title now uses the same file-safe PAPER-ID as the PDF name. `prepare_ingest` now makes network
calls; lookups that found the paper are remembered while the server runs, so `trust_check`, `fetch_pdf` and `prepare_ingest`
share one set of API calls.

**Breaking:** the `fetch_pdf` tool no longer takes `dest_dir`; PDFs always go into the brain's `assets/papers/` (without a
brain, the cache dir). An agent steered by text in a fetched abstract could otherwise pick where files are written. The CLI
keeps `--dest`.

Fixes:
- `trust_check` no longer reports OpenAlex's split preprint citation count as `citations`.
- `fetch_pdf` falls back to OpenAlex when Semantic Scholar is down or rate-limited.
- `trust_check` finds the retraction status of arXiv papers published in a journal: OpenAlex is asked under the
  journal DOI first, the arXiv DOI second.
- The highlights embed of a paper ingested before its PDF now matches the PDF name for DOI-only papers and old-style arXiv ids.
- Search and `trust_check` results carry the OpenAlex signals (`retracted`, `source_type`, ...).

### v0.1.0

First release. Five tools (`search_papers`, `trust_check`, `fetch_pdf`, `prepare_ingest`, `lint`), a CLI and tests at
every seam (170 offline tests, 3 opt-in live tests).

- Search across arXiv, Semantic Scholar and OpenAlex, merged and de-duplicated.
- Trust verdict HIGH/MEDIUM/LOW with reasons, using Semantic Scholar and OpenAlex (retraction flag); venues in `venues.toml`.
- `prepare_ingest` validates against the brain's `AGENTS.md`/`Templates`, refuses when Logseq has a different graph open and returns the calls for `mcp-logseq`.
- `lint` checks schema, PDF paths, backlinks, Related Pages links, empty highlights, staleness, Index coverage, `AGENTS.md`/`Templates` drift and page file names (duplicate files for one page, `___` names that Logseq will not read as `/`).

Verified live (2026-10-08): the open-graph check, and that `create_page` of `mcp-logseq` 1.10.0 writes the properties at the top of
the file, with six papers ingested into a real graph. Known limits: Semantic Scholar throttles anonymous clients (set `S2_API_KEY`);
`radiation-brain` needs its own `AGENTS.md` first; if a graph has `___` page files but no `:file-name-format :triple-lowbar` in
`logseq/config.edn`, an append through `mcp-logseq` to such a page creates a new `%2F` file instead (`lint` flags this).
