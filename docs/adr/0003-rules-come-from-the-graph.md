# 0003 — Rules are read from the graph

Status: accepted

The taxonomy is parsed from the `topic::` line of the brain's `AGENTS.md`; the page skeleton comes from its `Templates` page. A missing or unparseable `AGENTS.md` is a hard error with a clear message (no built-in fallback schema, so defaults cannot drift silently). `lint` reports drift between `AGENTS.md` and `Templates` (e.g. `desktop-architecture` is missing from `Templates` today). `radiation-brain` has no `AGENTS.md` yet and is unsupported until it gets one.
