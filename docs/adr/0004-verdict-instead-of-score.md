# 0004 — trust_check returns a verdict, not a score

Status: accepted

`AGENTS.md` defines HIGH / MEDIUM / LOW. `trust_check` returns `verdict` plus `reasons[]` and the raw signals. Reputable and suspect venues live in `venues.toml`, editable without code changes. Retractions are not checked yet (Crossref is a later option). The verdict is a proposal.
