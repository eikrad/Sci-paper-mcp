import httpx
import pytest
import respx

from sci_paper_mcp import core, sources

ATOM = """<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/abs/2005.11401v4</id><published>2020-05-22T00:00:00Z</published>
<title>Retrieval-Augmented
 Generation</title><summary>An abstract.</summary>
<author><name>P. Lewis</name></author></entry></feed>"""


@respx.mock
def test_search_merges_sources():
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


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)


@pytest.mark.parametrize(
    "venue,expected",
    [
        ("Conference on Empirical Methods in Natural Language Processing", "HIGH"),
        ("Annual Meeting of the Association for Computational Linguistics", "HIGH"),
        ("Social Science Computer Review", "MEDIUM"),
        ("Oracle Journal", "MEDIUM"),
    ],
)
@respx.mock
def test_venue_matching(venue, expected):
    _oa()
    _s2("DOI:10.1/x", venue=venue, authors=[{"name": "A B"}])
    assert core.trust_check("10.1/x")["verdict"] == expected


@respx.mock
def test_search_survives_one_source_down():
    respx.get(sources.ARXIV_API).respond(text=ATOM)
    respx.get(f"{sources.S2_API}/paper/search").respond(429)
    out = core.search_papers("rag")
    assert out["results"][0]["source"] == "arxiv" and "semantic_scholar" in out["warnings"][0]


@respx.mock
def test_s2_retries_on_429(monkeypatch):
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    route = respx.get(f"{sources.S2_API}/paper/DOI:10.1/x")
    route.side_effect = [httpx.Response(429), httpx.Response(200, json={"title": "T"})]
    assert sources.get_s2_paper("10.1/x")["title"] == "T"


@respx.mock
def test_s2_gives_up_with_hint(monkeypatch):
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    monkeypatch.delenv("S2_API_KEY", raising=False)
    respx.get(f"{sources.S2_API}/paper/DOI:10.1/x").respond(429)
    with pytest.raises(httpx.HTTPStatusError, match="S2_API_KEY"):
        sources.get_s2_paper("10.1/x")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://doi.org/10.1/abc", "DOI:10.1/abc"),
        ("arXiv:2005.11401v2", "ARXIV:2005.11401"),
        ("https://arxiv.org/pdf/2005.11401.pdf", "ARXIV:2005.11401"),
        ("abcdef0123", "abcdef0123"),
    ],
)
def test_identifier_mapping(raw, expected):
    assert sources.s2_identifier(raw) == expected


def _oa(status=404, **fields):
    respx.get(url__startswith=f"{sources.OPENALEX_API}/works/").respond(status, json=fields)


def _s2(path, **fields):
    respx.get(f"{sources.S2_API}/paper/{path}").respond(json={"title": "T", "year": 2020, **fields})


@respx.mock
def test_verdict_high_for_reputable_venue():
    _oa()
    _s2("DOI:10.1/x", venue="Advances in NeurIPS", authors=[{"name": "A B", "hIndex": 5}])
    r = core.trust_check("10.1/x")
    assert r["verdict"] == "HIGH" and r["peer_reviewed"]


@respx.mock
def test_verdict_medium_for_known_author_preprint():
    _oa()
    _s2(
        "ARXIV:2005.11401",
        venue="arXiv.org",
        externalIds={"ArXiv": "2005.11401"},
        authors=[{"name": "A B", "hIndex": 40}],
    )
    assert core.trust_check("2005.11401")["verdict"] == "MEDIUM"


@respx.mock
def test_verdict_low_for_unknown_preprint():
    _oa()
    _s2(
        "ARXIV:2005.11401",
        venue="",
        externalIds={"ArXiv": "2005.11401"},
        authors=[{"name": "A B", "hIndex": 1}],
    )
    assert core.trust_check("2005.11401")["verdict"] == "LOW"


@respx.mock
def test_verdict_low_when_not_found():
    _oa()
    respx.get(f"{sources.S2_API}/paper/DOI:10.1/nope").respond(404)
    r = core.trust_check("10.1/nope")
    assert r["verdict"] == "LOW" and not r["found"]


@respx.mock
def test_fetch_pdf_names_after_paper_id(tmp_path):
    respx.get("https://arxiv.org/pdf/2005.11401").respond(content=b"%PDF-1.5 data")
    out = core.fetch_pdf("arXiv:2005.11401", "RAG-Lewis2020", str(tmp_path))
    assert out["path"].endswith("RAG-Lewis2020-2005.11401.pdf")


@respx.mock
def test_fetch_pdf_derives_paper_id_and_writes_to_brain(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_PATH", str(tmp_path))
    _s2("ARXIV:2005.11401", externalIds={"ArXiv": "2005.11401"}, authors=[{"name": "Patrick Lewis"}])
    respx.get("https://arxiv.org/pdf/2005.11401").respond(content=b"%PDF-1")
    out = core.fetch_pdf("2005.11401")
    assert out["pdf_path_property"] == "../assets/papers/Lewis2020-2005.11401.pdf"
    assert (tmp_path / "assets/papers/Lewis2020-2005.11401.pdf").exists()


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
    with pytest.raises(RuntimeError, match="UNPAYWALL_EMAIL"):
        core.fetch_pdf("10.1/x")


@respx.mock
def test_retraction_from_openalex_forces_low():
    _s2("DOI:10.1/x", venue="NeurIPS", authors=[{"name": "A B", "hIndex": 50}])
    _oa(200, is_retracted=True, cited_by_count=3)
    r = core.trust_check("10.1/x")
    assert r["verdict"] == "LOW" and r["retracted"] is True and "retracted" in r["reasons"][0]


@respx.mock
def test_openalex_supplies_venue_when_s2_has_none():
    _s2("DOI:10.1/x", venue="", authors=[{"name": "A B"}])
    _oa(
        200,
        is_retracted=False,
        cited_by_count=7,
        primary_location={"source": {"type": "journal", "display_name": "Some Journal", "is_in_doaj": True}},
    )
    r = core.trust_check("10.1/x")
    assert r["venue"] == "Some Journal" and r["verdict"] == "MEDIUM" and r["in_doaj"] is True
    assert r["retracted"] is False


@respx.mock
def test_s2_down_openalex_still_answers():
    respx.get(f"{sources.S2_API}/paper/DOI:10.1/x").respond(429)
    _oa(
        200,
        display_name="T",
        publication_year=2021,
        is_retracted=False,
        cited_by_count=1,
        primary_location={"source": {"type": "conference", "display_name": "ICML"}},
    )
    r = core.trust_check("10.1/x")
    assert r["title"] == "T" and "semantic_scholar" in r["warnings"][0]


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
    route = respx.get(url__startswith=f"{sources.OPENALEX_API}/works/").respond(200, json={})
    core.trust_check("2005.11401")
    assert "10.48550/arXiv.2005.11401" in str(route.calls[0].request.url)


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
