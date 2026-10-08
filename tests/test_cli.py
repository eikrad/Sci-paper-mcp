import json

import respx
from conftest import paper_page

from sci_paper_mcp.cli import main


def run(capsys, *argv):
    code = main(list(argv))
    return code, capsys.readouterr()


def test_lint_on_healthy_brain_exits_zero(healthy_brain, capsys):
    code, out = run(capsys, "lint", "--brain", str(healthy_brain))
    assert code == 0
    assert json.loads(out.out)["findings"] == []


def test_lint_exits_one_on_errors(make_brain, capsys):
    brain = make_brain(pages={"Sources/Research/X": paper_page(drop=["url"])})
    code, out = run(capsys, "lint", "--brain", str(brain))
    assert code == 1
    assert json.loads(out.out)["summary"]["schema"] == 1


def test_lint_warnings_alone_do_not_fail_by_default(make_brain, capsys):
    brain = make_brain(
        pages={"Sources/Research/X": paper_page(), "Concepts/RAG": "- unrelated"},
        assets=["RAG-Lewis2020-2005.11401.pdf"],
    )
    code, _ = run(capsys, "lint", "--brain", str(brain))
    assert code == 0
    code, _ = run(capsys, "lint", "--brain", str(brain), "--fail-on", "warning")
    assert code == 1


def test_lint_without_a_schema_reports_a_clean_error(tmp_path, capsys):
    code, out = run(capsys, "lint", "--brain", str(tmp_path))
    assert code == 2
    assert "AGENTS.md" in out.err


@respx.mock
def test_pdf_goes_into_the_configured_brain(make_brain, monkeypatch, capsys):
    brain = make_brain()
    monkeypatch.setenv("SECOND_BRAIN_PATH", str(brain))
    respx.get("https://arxiv.org/pdf/2005.11401").respond(content=b"%PDF-1")
    code, out = run(capsys, "pdf", "2005.11401", "--paper-id", "X")
    assert code == 0
    assert json.loads(out.out)["pdf_path_property"] == "../assets/papers/X-2005.11401.pdf"
    assert (brain / "assets" / "papers" / "X-2005.11401.pdf").exists()
