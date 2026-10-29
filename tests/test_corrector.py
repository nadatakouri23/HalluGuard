"""
Unit tests for core.corrector.suggestion_engine
"""
from core.corrector.suggestion_engine import suggest
from core.scorer.hallucination_scorer import HallucinationIssue, HallucinationReport


class TestSuggestionEngine:
    """Test correction suggestion generation."""

    def test_known_pattern_match(self):
        """Tokens in the COMMON_PATTERNS dict should get a HIGH confidence suggestion."""
        report = HallucinationReport(
            hallucinations=[
                HallucinationIssue(
                    line=0,
                    issue_type="unknown_import",
                    token="beautifulsoup",
                    explanation="Not found",
                    suggestion="",
                    severity="HIGH",
                )
            ]
        )
        results = suggest(report, language="python")
        assert len(results) == 1
        assert results[0]["confidence"] == "HIGH"
        assert results[0]["suggestion"] == "beautifulsoup4"

    def test_fuzzy_match_import(self):
        """A slightly misspelled package should trigger a fuzzy suggestion."""
        report = HallucinationReport(
            hallucinations=[
                HallucinationIssue(
                    line=0,
                    issue_type="unknown_import",
                    token="reqeusts",  # typo
                    explanation="Not found",
                    suggestion="",
                    severity="HIGH",
                )
            ]
        )
        results = suggest(report, language="python")
        assert len(results) == 1
        assert results[0]["suggestion"] == "requests"

    def test_unknown_function_suggestion(self):
        report = HallucinationReport(
            hallucinations=[
                HallucinationIssue(
                    line=5,
                    issue_type="unknown_function",
                    token="fetchUserData",
                    explanation="Not found",
                    suggestion="",
                    severity="MEDIUM",
                )
            ]
        )
        results = suggest(report, language="python")
        assert len(results) == 1
        assert results[0]["confidence"] in ("HIGH", "MEDIUM")

    def test_no_match(self):
        """Completely random tokens should get a LOW confidence result."""
        report = HallucinationReport(
            hallucinations=[
                HallucinationIssue(
                    line=0,
                    issue_type="unknown_import",
                    token="zzzzzzzzzzznopackage",
                    explanation="Not found",
                    suggestion="",
                    severity="HIGH",
                )
            ]
        )
        results = suggest(report, language="python")
        assert len(results) == 1
        assert results[0]["confidence"] == "LOW"

    def test_empty_report(self):
        report = HallucinationReport(hallucinations=[])
        results = suggest(report, language="python")
        assert results == []
