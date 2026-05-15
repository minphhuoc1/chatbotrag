from pathlib import Path


def _read_app() -> str:
    return Path("app.py").read_text(encoding="utf-8")


def test_app_uses_structured_entrypoint():
    """D3: UI path must call run_structured() instead of raw analyzer/reasoner chains."""
    content = _read_app()
    assert "engine.run_structured(" in content
    assert "engine.analyzer_chain.invoke(" not in content
    assert "engine.reasoner_chain.invoke(" not in content
    assert "analysis.get(" not in content


def test_app_keeps_evidence_render_helpers():
    """B2: Evidence rendering helpers must stay present after refactor."""
    content = _read_app()
    assert "def _build_doc_evidence_rows(" in content
    assert "def _build_grounding_rows(" in content
