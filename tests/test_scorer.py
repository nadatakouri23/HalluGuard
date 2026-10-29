"""
Unit tests for core.scorer.hallucination_scorer
"""
from core.scorer.hallucination_scorer import HallucinationReport, compute


class TestScorer:
    """Test scoring logic."""

    def test_clean_code_zero_score(self):
        tokens = {"imports": ["os"], "function_calls": ["print"], "from_imports": []}
        knowledge = {"verified_imports": {"os": {"exists": True, "type": "stdlib"}}}
        report = compute(tokens, knowledge)
        assert isinstance(report, HallucinationReport)
        assert report.risk_score == 0
        assert len(report.hallucinations) == 0

    def test_unknown_import_high_penalty(self):
        tokens = {"imports": ["fakepkg"], "function_calls": [], "from_imports": []}
        knowledge = {"verified_imports": {"fakepkg": {"exists": False}}}
        report = compute(tokens, knowledge)
        assert report.risk_score > 0
        assert any(h.issue_type == "unknown_import" for h in report.hallucinations)

    def test_unknown_function_penalty(self):
        tokens = {
            "imports": [],
            "function_calls": ["fetchUserData"],
            "from_imports": [],
        }
        knowledge = {"verified_imports": {}}
        report = compute(tokens, knowledge)
        assert report.risk_score > 0
        assert any(h.issue_type == "unknown_function" for h in report.hallucinations)

    def test_multiple_issues_stack(self):
        tokens = {
            "imports": ["fake1", "fake2"],
            "function_calls": ["nonExistentFunc"],
            "from_imports": [],
        }
        knowledge = {
            "verified_imports": {
                "fake1": {"exists": False},
                "fake2": {"exists": False},
            }
        }
        report = compute(tokens, knowledge)
        assert report.risk_score > 30
        assert len(report.hallucinations) >= 3

    def test_rwkv_score_integration(self):
        tokens = {"imports": ["fake"], "function_calls": [], "from_imports": []}
        knowledge = {"verified_imports": {"fake": {"exists": False}}}
        report = compute(tokens, knowledge, rwkv_score=80.0)
        assert isinstance(report.risk_score, int)

    def test_report_to_dict(self):
        tokens = {"imports": ["fake"], "function_calls": [], "from_imports": []}
        knowledge = {"verified_imports": {"fake": {"exists": False}}}
        report = compute(tokens, knowledge)
        d = report.to_dict()
        assert "risk_score" in d
        assert "hallucinations" in d
        assert isinstance(d["hallucinations"], list)

    def test_custom_weights(self):
        tokens = {"imports": ["fake"], "function_calls": [], "from_imports": []}
        knowledge = {"verified_imports": {"fake": {"exists": False}}}
        report = compute(tokens, knowledge, weights={"knowledge": 1.0, "ast": 0.0, "rwkv": 0.0})
        # With only the knowledge source active, the score is the knowledge score:
        # one fabricated import = 81 (concave scale; it used to be a flat 100/N).
        assert report.risk_score == 81
        assert report.severity == "HIGH"
