# 0005 — OpenAlex supplements Semantic Scholar in trust_check

Status: accepted. Extends 0004.

`trust_check` always queries both sources and merges: Semantic Scholar supplies venue, citations, influential citations and author h-index; OpenAlex supplies `is_retracted`, source type and DOAJ status. Either may fail independently, which yields a warning instead of an error; both failing is an error. A retraction forces LOW. If OpenAlex is unavailable, `retracted` is `null` and a reason says retraction status is unknown. arXiv ids are looked up through their DataCite DOI (`10.48550/arXiv.<id>`). `fetch_pdf` takes its metadata from the same lookup, so a rate-limited Semantic Scholar still yields a PAPER-ID and PDF link, except when an arXiv id and a `paper_id` are given, which need no lookup.

OpenAlex citation counts for preprints are split across versions (18 vs 895 for the same paper) and are reported separately as `citations_openalex`, never used for the verdict. OpenAlex no longer honours `mailto`; a free key (`OPENALEX_API_KEY`) raises the budget, but anonymous use works. API keys are sent only to their own service.

`search_papers` also queries OpenAlex, so a rate-limited Semantic Scholar still yields venue and DOI. Duplicates are merged with Semantic Scholar first, OpenAlex second and arXiv last; lower sources fill fields the winner lacks. For preprints (OpenAlex source type "repository") the venue and citation count are dropped, since the repository is not a venue and counts are split across versions. A search costs OpenAlex budget (about $0.001 per call).
