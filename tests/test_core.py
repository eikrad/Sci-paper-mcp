import httpx
import pytest
import respx

from sci_paper_mcp import core, sources
from sci_paper_mcp.sources import Identifier

ATOM = """<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/abs/2005.11401v4</id><published>2020-05-22T00:00:00Z</published>
<title>Retrieval-Augmented
 Generation</title><summary>An abstract.</summary>
<author><name>P. Lewis</name></author></entry></feed>"""
JOURNAL_WORK = {
    "id": "https://openalex.org/W1",
    "doi": "https://doi.org/10.1109/TDSC.2026.3695553",
    "display_name": "MCPXkit",
    "publication_year": 2026,
    "is_retracted": True,
    "authorships": [{"author": {"display_name": "Yongjian Guo"}}],
    "cited_by_count": 4,
    "abstract_inverted_index": {"A": [0], "toolkit": [1], "for": [2], "MCP": [3]},
    "primary_location": {
        "pdf_url": None,
        "source": {
            "type": "journal",
            "display_name": "IEEE Transactions on Dependable and Secure Computing",
            "is_in_doaj": False,
        },
    },
    "best_oa_location": {"pdf_url": "https://example.org/mcpxkit.pdf"},
}
ARXIV_WORK = {
    "doi": "https://doi.org/10.48550/arxiv.2604.07551",
    "display_name": "MCP-DPT",
    "publication_year": 2026,
    "authorships": [{"author": {"display_name": "M. Rostamzadeh"}}],
    "cited_by_count": 18,
    "abstract_inverted_index": None,
    "primary_location": {
        "pdf_url": "https://arxiv.org/pdf/2604.07551",
        "source": {"type": "repository", "display_name": "arXiv (Cornell University)"},
    },
}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)


def _oa_search(*works, status=200):
    return respx.get(f"{sources.OPENALEX_API}/works").respond(status, json={"results": list(works)})


def _oa(status=404, **fields):
    return respx.get(url__startswith=f"{sources.OPENALEX_API}/works/").respond(status, json=fields)


def _s2(path, **fields):
    respx.get(f"{sources.S2_API}/paper/{path}").respond(json={"title": "T", "year": 2020, **fields})


@respx.mock
def test_search_merges_sources():
    _oa_search()
    respx.get(sources.ARXIV_API).respond(text=ATOM)
    respx.get(f"{sources.S2_API}/paper/search").respond(
        json={
            "data": [
                {
                    "paperId": "x",
                    "title": "Retrieval-Augmented Generation",
                    "year": 2020,
                    "authors": [{"name": "P. Lewis"}],
                    "venue": "NeurIPS",
                    "externalIds": {"ArXiv": "2005.11401"},
                    "citationCount": 5000,
                }
            ]
        }
    )
    res = core.search_papers("rag")["results"]
    assert len(res) == 1
    assert res[0]["venue"] == "NeurIPS" and res[0]["pdf_url"].endswith("2005.11401")


@respx.mock
def test_search_survives_one_source_down():
    _oa_search()
    respx.get(sources.ARXIV_API).respond(text=ATOM)
    respx.get(f"{sources.S2_API}/paper/search").respond(429)
    out = core.search_papers("rag")
    assert out["results"][0]["source"] == "arxiv" and "semantic_scholar" in out["warnings"][0]


@pytest.mark.parametrize(
    "raw,kind,value",
    [
        ("https://doi.org/10.1/abc", "doi", "10.1/abc"),
        (" http://dx.doi.org/10.1/abc ", "doi", "10.1/abc"),
        ("arXiv:2005.11401v2", "arxiv", "2005.11401"),
        ("https://arxiv.org/pdf/2005.11401.pdf", "arxiv", "2005.11401"),
        ("hep-th/9901001v2", "arxiv", "hep-th/9901001"),
        ("abcdef0123", "s2", "abcdef0123"),
    ],
)
def test_identifier_is_parsed_once(raw, kind, value):
    assert Identifier.parse(raw) == Identifier(kind, value)


@respx.mock
def test_s2_retries_on_429():
    route = respx.get(f"{sources.S2_API}/paper/DOI:10.1/x")
    route.side_effect = [httpx.Response(429), httpx.Response(200, json={"title": "T"})]
    assert sources.get_s2_paper(Identifier.parse("10.1/x")).title == "T"


@respx.mock
def test_s2_gives_up_with_hint(monkeypatch):
    monkeypatch.delenv("S2_API_KEY", raising=False)
    respx.get(f"{sources.S2_API}/paper/DOI:10.1/x").respond(429)
    with pytest.raises(httpx.HTTPStatusError, match="S2_API_KEY"):
        sources.get_s2_paper(Identifier.parse("10.1/x"))


@respx.mock
def test_s2_key_not_sent_to_arxiv(monkeypatch):
    monkeypatch.setenv("S2_API_KEY", "secret")
    route = respx.get(sources.ARXIV_API).respond(text=ATOM)
    sources.search_arxiv("rag", 1)
    assert "x-api-key" not in route.calls[0].request.headers


@pytest.mark.parametrize(
    "query,expected",
    [
        ("model context protocol security", "all:model AND all:context AND all:protocol AND all:security"),
        ('security "model context protocol"', 'all:security AND all:"model context protocol"'),
        ("  rag  ", "all:rag"),
    ],
)
@respx.mock
def test_arxiv_query_requires_every_term_to_match(query, expected):
    route = respx.get(sources.ARXIV_API).respond(text="<feed xmlns='http://www.w3.org/2005/Atom'/>")
    sources.search_arxiv(query, 3)
    assert route.calls[0].request.url.params["search_query"] == expected


@respx.mock
def test_openalex_journal_work_is_mapped():
    _oa_search(JOURNAL_WORK)
    [p] = sources.search_openalex("mcp", 5)
    assert p.doi == "10.1109/tdsc.2026.3695553" and p.arxiv_id is None
    assert p.venue == "IEEE Transactions on Dependable and Secure Computing"
    assert p.abstract == "A toolkit for MCP" and p.citations == 4
    assert p.authors == ["Yongjian Guo"] and p.pdf_url == "https://example.org/mcpxkit.pdf"
    assert p.source == "openalex"
    assert (p.source_type, p.retracted, p.in_doaj) == ("journal", True, False)
    assert (p.citations_openalex, p.openalex_id) == (4, "https://openalex.org/W1")


@respx.mock
def test_openalex_preprint_has_no_venue_and_untrusted_citations():
    _oa_search(ARXIV_WORK)
    [p] = sources.search_openalex("mcp", 5)
    assert p.arxiv_id == "2604.07551" and p.doi is None
    assert p.venue is None and p.citations is None  # counts are split across versions
    assert p.citations_openalex == 18 and p.source_type == "repository"
    assert p.pdf_url == "https://arxiv.org/pdf/2604.07551"


@respx.mock
def test_openalex_search_sends_query_and_limit():
    route = _oa_search()
    sources.search_openalex("model context protocol", 7)
    params = route.calls[0].request.url.params
    assert params["search"] == "model context protocol" and params["per_page"] == "7"


@respx.mock
def test_search_merges_openalex_venue_into_the_arxiv_hit():
    arxiv = ATOM.replace("2005.11401", "2604.07551")
    respx.get(sources.ARXIV_API).respond(text=arxiv)
    respx.get(f"{sources.S2_API}/paper/search").respond(429)
    journal = JOURNAL_WORK | {"doi": "https://doi.org/10.48550/arxiv.2604.07551"}
    journal["primary_location"] = {"pdf_url": None, "source": {"type": "journal", "display_name": "TDSC"}}
    _oa_search(journal)
    out = core.search_papers("rag")
    [p] = out["results"]
    assert p["arxiv_id"] == "2604.07551" and p["venue"] == "TDSC" and p["abstract"]
    assert p["pdf_url"] and any("semantic_scholar" in w for w in out["warnings"])


@respx.mock
def test_search_survives_openalex_being_down():
    respx.get(sources.ARXIV_API).respond(text=ATOM)
    respx.get(f"{sources.S2_API}/paper/search").respond(json={"data": []})
    _oa_search(status=500)
    out = core.search_papers("rag")
    assert out["results"] and any("openalex" in w for w in out["warnings"])


@respx.mock
def test_trust_check_merges_both_sources():
    _s2(
        "DOI:10.1/x",
        paperId="p1",
        venue="",
        citationCount=9,
        influentialCitationCount=2,
        authors=[{"name": "A B", "hIndex": 12}, {"name": "C D", "hIndex": 3}],
    )
    _oa(
        200,
        id="https://openalex.org/W1",
        is_retracted=False,
        cited_by_count=7,
        primary_location={"source": {"type": "journal", "display_name": "Some Journal", "is_in_doaj": True}},
    )
    r = core.trust_check("10.1/x")
    assert r["venue"] == "Some Journal" and r["verdict"] == "MEDIUM" and r["peer_reviewed"]
    assert r["retracted"] is False and r["in_doaj"] is True and r["source_type"] == "journal"
    assert (r["citations"], r["citations_openalex"]) == (9, 7)
    assert (r["influential_citations"], r["max_author_h_index"]) == (2, 12)
    assert r["semantic_scholar_url"].endswith("/p1") and r["openalex_id"].endswith("/W1")


@respx.mock
def test_paper_unknown_to_both_sources_is_not_found():
    _oa()
    respx.get(f"{sources.S2_API}/paper/DOI:10.1/nope").respond(404)
    outcomes = {"semantic_scholar": "not_found", "openalex": "not_found"}
    assert core.lookup("10.1/nope") == core.Lookup(None, outcomes, [])
    r = core.trust_check("10.1/nope")
    assert r["verdict"] == "LOW" and not r["found"]


@respx.mock
def test_s2_down_and_openalex_not_knowing_the_paper_is_an_error():
    respx.get(f"{sources.S2_API}/paper/DOI:10.1/x").respond(429)
    _oa()
    with pytest.raises(RuntimeError, match="semantic_scholar"):
        core.lookup("10.1/x")


@respx.mock
def test_s2_down_openalex_still_answers():
    respx.get(f"{sources.S2_API}/paper/DOI:10.1/x").respond(429)
    _oa(
        200,
        display_name="T",
        publication_year=2021,
        is_retracted=False,
        cited_by_count=1,
        authorships=[{"author": {"display_name": "Ada Lovelace"}}],
        primary_location={"source": {"type": "conference", "display_name": "ICML"}},
    )
    r = core.trust_check("10.1/x")
    assert r["title"] == "T" and "semantic_scholar" in r["warnings"][0]
    assert r["verdict"] == "HIGH"  # OpenAlex alone now knows the authors


@respx.mock
def test_openalex_source_types_beyond_journal_and_conference_supply_a_venue():
    respx.get(f"{sources.S2_API}/paper/DOI:10.1/x").respond(404)
    _oa(200, primary_location={"source": {"type": "book series", "display_name": "Lecture Notes in CS"}})
    r = core.trust_check("10.1/x")
    assert r["venue"] == "Lecture Notes in CS" and r["peer_reviewed"] and r["source_type"] == "book series"


@respx.mock
def test_openalex_preprint_count_never_becomes_citations():
    respx.get(f"{sources.S2_API}/paper/ARXIV:2604.07551").respond(429)
    _oa(200, **ARXIV_WORK | {"is_retracted": False})
    r = core.trust_check("2604.07551")
    assert r["citations"] is None and r["citations_openalex"] == 18


@respx.mock
def test_openalex_down_flags_unknown_retraction():
    _s2("DOI:10.1/x", venue="ICML", authors=[{"name": "A B"}])
    _oa(500)
    r = core.trust_check("10.1/x")
    assert r["verdict"] == "HIGH" and r["retracted"] is None
    assert any("retraction status unknown" in x for x in r["reasons"])


@respx.mock
def test_both_sources_down_raises():
    respx.get(f"{sources.S2_API}/paper/DOI:10.1/x").respond(429)
    _oa(500)
    with pytest.raises(RuntimeError, match="semantic_scholar"):
        core.trust_check("10.1/x")


@respx.mock
def test_arxiv_id_maps_to_datacite_doi_for_openalex():
    _s2(
        "ARXIV:2005.11401",
        venue="",
        externalIds={"ArXiv": "2005.11401"},
        authors=[{"name": "A", "hIndex": 30}],
    )
    route = _oa(200)
    core.trust_check("2005.11401")
    assert "10.48550/arXiv.2005.11401" in str(route.calls[0].request.url)


@respx.mock
def test_paper_missing_in_openalex_is_not_reported_as_an_outage():
    _s2("ARXIV:2512.08290", venue="arXiv.org", externalIds={"ArXiv": "2512.08290"}, authors=[{"name": "A"}])
    _oa(404)
    r = core.trust_check("2512.08290")
    assert r["retracted"] is None and r["warnings"] == []
    assert any("not found in OpenAlex" in x for x in r["reasons"])
    assert not any("unavailable" in x for x in r["reasons"])


@respx.mock
def test_openalex_outage_is_reported_as_unavailable():
    _s2("ARXIV:2512.08290", venue="arXiv.org", externalIds={"ArXiv": "2512.08290"}, authors=[{"name": "A"}])
    _oa(500)
    r = core.trust_check("2512.08290")
    assert any("OpenAlex unavailable" in x for x in r["reasons"]) and r["warnings"]


@respx.mock
def test_bare_s2_id_reaches_openalex_only_through_the_doi_s2_returns():
    _s2("abcdef0123", venue="ICML", authors=[{"name": "A B"}])
    out = core.lookup("abcdef0123")
    assert out.outcomes == {"semantic_scholar": "found", "openalex": "skipped"}
    assert any("no DOI or arXiv id" in x for x in core.trust_check("abcdef0123")["reasons"])

    _s2("abcdef0124", externalIds={"DOI": "10.1/y"})
    route = _oa(200, is_retracted=False)
    out = core.lookup("abcdef0124")
    assert out.outcomes["openalex"] == "found" and "doi.org/10.1/y" in str(route.calls[0].request.url)


@pytest.mark.parametrize(
    "raw,s2_path,field,value",
    [
        ("https://arxiv.org/abs/2005.11401v3", "ARXIV:2005.11401", "arxiv_id", "2005.11401"),
        ("https://doi.org/10.1/x", "DOI:10.1/x", "doi", "10.1/x"),
    ],
)
@respx.mock
def test_lookup_fills_ids_from_the_identifier(raw, s2_path, field, value):
    _s2(s2_path)
    _oa()
    assert getattr(core.lookup(raw).paper, field) == value


@respx.mock
def test_fetch_pdf_names_after_paper_id(tmp_path):
    respx.get("https://arxiv.org/pdf/2005.11401").respond(content=b"%PDF-1.5 data")
    out = core.fetch_pdf("arXiv:2005.11401", "RAG-Lewis2020", str(tmp_path))
    assert out["path"].endswith("RAG-Lewis2020-2005.11401.pdf")


@respx.mock
def test_fetch_pdf_derives_paper_id_and_writes_to_brain(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_PATH", str(tmp_path))
    _s2("ARXIV:2005.11401", externalIds={"ArXiv": "2005.11401"}, authors=[{"name": "Patrick Lewis"}])
    _oa()
    respx.get("https://arxiv.org/pdf/2005.11401").respond(content=b"%PDF-1")
    out = core.fetch_pdf("2005.11401")
    assert out["pdf_path_property"] == "../assets/papers/Lewis2020-2005.11401.pdf"
    assert (tmp_path / "assets/papers/Lewis2020-2005.11401.pdf").exists()


@respx.mock
def test_fetch_pdf_falls_back_to_openalex_when_s2_is_down(tmp_path):
    respx.get(f"{sources.S2_API}/paper/DOI:10.1/x").respond(429)
    _oa(
        200,
        doi="https://doi.org/10.1/x",
        display_name="On Engines",
        publication_year=2024,
        authorships=[{"author": {"display_name": "Ada Lovelace"}}],
        best_oa_location={"pdf_url": "https://example.org/x.pdf"},
    )
    respx.get("https://example.org/x.pdf").respond(content=b"%PDF-1")
    out = core.fetch_pdf("10.1/x", dest_dir=str(tmp_path))
    assert out["paper_id"] == "Lovelace2024" and out["url"] == "https://example.org/x.pdf"
    assert (tmp_path / "Lovelace2024-10.1_x.pdf").exists()


@respx.mock
def test_fetch_pdf_of_an_unknown_paper_says_so(tmp_path):
    respx.get(f"{sources.S2_API}/paper/DOI:10.1/nope").respond(404)
    _oa()
    with pytest.raises(RuntimeError, match="not found"):
        core.fetch_pdf("10.1/nope", dest_dir=str(tmp_path))


@respx.mock
def test_fetch_pdf_never_overwrites(tmp_path):
    respx.get("https://arxiv.org/pdf/2005.11401").respond(content=b"%PDF-1")
    core.fetch_pdf("2005.11401", "X", str(tmp_path))
    with pytest.raises(RuntimeError, match="already exists"):
        core.fetch_pdf("2005.11401", "X", str(tmp_path))


@respx.mock
def test_fetch_pdf_rejects_html(tmp_path):
    respx.get("https://arxiv.org/pdf/2005.11401").respond(content=b"<html>")
    with pytest.raises(RuntimeError):
        core.fetch_pdf("2005.11401", "X", str(tmp_path))


@respx.mock
def test_unpaywall_needs_email(monkeypatch):
    monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)
    _s2("DOI:10.1/x", externalIds={"DOI": "10.1/x"}, authors=[{"name": "A B"}])
    _oa()
    with pytest.raises(RuntimeError, match="UNPAYWALL_EMAIL"):
        core.fetch_pdf("10.1/x")
