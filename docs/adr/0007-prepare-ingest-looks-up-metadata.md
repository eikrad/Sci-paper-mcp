# 0007 — prepare_ingest looks up the metadata itself

Status: accepted. Refines 0001.

`prepare_ingest` took twenty parameters. Ten were not judgement but metadata the agent copied from `trust_check` (title, authors, venue, year, citations, `peer_reviewed`, Semantic Scholar link, arXiv id, DOI) and from `fetch_pdf` (`pdf_path_property`). The copy is where errors entered: `trust_check` once reported OpenAlex's split preprint citation count as `citations`, and the agent wrote it onto the page. ADR 0001 gives the agent content and judgement and the server validation and rendering; metadata is neither, so the server should own it.

`prepare_ingest` therefore takes the `identifier` (DOI, arXiv id or S2 id) plus the judgement (topic, verdict and its reasoning, key points, relevance, related pages; optionally language, code URL and PAPER-ID). It runs `core.lookup` itself, so the page shows the same merged Paper that `trust_check` and `fetch_pdf` see, with `peer_reviewed` as `not is_preprint(paper)`. It finds the PDF in the raw layer itself (`Brain.find_pdf`): the file named `<PAPER-ID>-<id>.pdf` for any of the paper's ids, compared case-insensitively because OpenAlex lowercases DOIs. Page title and PDF name share one PAPER-ID (`resolve_paper_id`), derived as in `fetch_pdf` when omitted. The agent can override only the abstract; without one from either side the section stays empty with a warning. Bad input (graph, topic, language, verdict, an existing page for a given PAPER-ID) is refused before the lookup, so it costs no network call.

`core.lookup` remembers a lookup in-process only when the paper was found and no source failed. Failures and unknown papers are never remembered, there is no disk cache, and every caller gets a copy, so mutating a Paper cannot corrupt the memo.

Consequences:
- Breaks v0.1.0 callers of the tool: the metadata parameters and `pdf_path` are gone, `identifier` is required, `paper_id` is optional and the page title now goes through the same file-safe PAPER-ID as the PDF.
- `prepare_ingest` now makes network calls and fails when every source is down. `trust_check`, `fetch_pdf` and `prepare_ingest` would triple the load on an anonymous Semantic Scholar; the memo softens that. A remembered lookup is not refreshed until the server restarts.
- The agent can no longer correct the metadata on the page; fix it at the source or edit the page afterwards.
- A PDF saved under a non-standard name is not found: the page says "not found" until the file is renamed.
- A paper with neither DOI nor arXiv id is refused, since `document-id` needs one.
