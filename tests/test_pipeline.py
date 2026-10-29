"""
End-to-end integration tests for core.pipeline
"""
from core.pipeline import analyze
from core.scorer.hallucination_scorer import HallucinationReport


class TestPythonPipeline:
    """Integration tests for Python analysis."""

    def test_clean_python_code(self):
        code = "import os\nprint(os.getcwd())"
        report = analyze(code, language="python")
        assert isinstance(report, HallucinationReport)
        assert report.risk_score == 0
        assert len(report.hallucinations) == 0

    def test_hallucinated_import(self):
        code = "import this_does_not_exist_xyz\nthis_does_not_exist_xyz.run()"
        report = analyze(code, language="python")
        assert report.risk_score > 0
        assert any(h.issue_type == "unknown_import" for h in report.hallucinations)

    def test_suggestions_generated(self):
        code = "import reqeusts\nreqeusts.get('http://x.com')"
        report = analyze(code, language="python")
        assert len(report.suggestions) > 0

    def test_report_serialization(self):
        code = "import fake_pkg_xyz"
        report = analyze(code, language="python")
        d = report.to_dict()
        assert "risk_score" in d
        assert "hallucinations" in d
        assert "suggestions" in d
        assert d["file"] == "snippet.py"


class TestJavaScriptPipeline:
    """Integration tests for JavaScript analysis."""

    def test_clean_js_code(self):
        code = "import express from 'express';\nconsole.log('hi');"
        report = analyze(code, language="javascript")
        assert isinstance(report, HallucinationReport)

    def test_hallucinated_npm_package(self):
        code = "import magic from 'totally-nonexistent-pkg-abc';"
        report = analyze(code, language="javascript")
        assert report.risk_score > 0
        assert any(h.issue_type == "unknown_import" for h in report.hallucinations)

    def test_js_file_extension(self):
        code = "console.log('test');"
        report = analyze(code, language="js")
        assert report.file == "snippet.js"

    def test_ts_file_extension(self):
        code = "console.log('test');"
        report = analyze(code, language="typescript")
        assert report.file == "snippet.ts"


class TestUnsupported:
    """Test unsupported language handling."""

    def test_unsupported_language_raises(self):
        import pytest
        with pytest.raises(ValueError, match="Unsupported language"):
            analyze("code", language="rust")
