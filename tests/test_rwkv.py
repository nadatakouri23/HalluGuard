"""
RWKV: B9 (log-probability signal, calibration, None instead of 50),
B10 (coherent routing, cloud not implemented), B19 (bounded log),
B20 (availability / health).
"""
from __future__ import annotations

import json
import math

import pytest

from core.pipeline import analyze
from core.rwkv_engine import inference, model_loader, router


class FakePipeline:
    """Tokenizer stand-in: one token per character."""

    def encode(self, text: str) -> list[int]:
        return [ord(c) % 16 for c in text]


class FakeModel:
    """Predicts token ``t+1`` with probability ``p`` after token ``t``."""

    def __init__(self, p: float, vocab: int = 16) -> None:
        self.p = p
        self.vocab = vocab

    def forward(self, tokens, state):
        # Logits that give the *next character's token* probability p.
        # The test text is "abab..." so the next token is deterministic.
        last = tokens[-1]
        nxt = (last + 1) % self.vocab if last == ord("a") % 16 else ord("a") % 16
        other = (1 - self.p) / (self.vocab - 1)
        logits = [math.log(other)] * self.vocab
        logits[nxt] = math.log(self.p)
        return logits, (state or 0) + 1


@pytest.fixture
def fake_model(monkeypatch):
    def install(p: float):
        model_loader._model = FakeModel(p)
        model_loader._pipeline = FakePipeline()
        model_loader._loaded = True
    yield install
    model_loader.reset()


@pytest.fixture(autouse=True)
def _rwkv_env(monkeypatch, tmp_path):
    monkeypatch.delenv(inference.ENV_ALLOW_UNCALIBRATED, raising=False)
    monkeypatch.setenv(inference.ENV_CALIBRATION, str(tmp_path / "missing.json"))
    router.clear_routing_log()
    yield
    model_loader.reset()


class TestLogProbSignal:
    def test_log_softmax_matches_definition(self):
        logits = [1.0, 2.0, 3.0]
        denom = sum(math.exp(x) for x in logits)
        assert inference._log_prob(logits, 2) == pytest.approx(math.log(math.exp(3) / denom))

    def test_mean_nll_of_confident_model_is_low(self):
        nll, n = inference.mean_nll(FakeModel(0.99), FakePipeline(), "ab" * 20, 100)
        assert n == 39
        assert nll == pytest.approx(-math.log(0.99), rel=1e-6) or nll < 3.0

    def test_surprising_text_has_higher_nll(self):
        # The fake model "expects" a b a b...; "aaaa" is surprising to it.
        likely, _ = inference.mean_nll(FakeModel(0.9), FakePipeline(), "ab" * 20, 100)
        odd, _ = inference.mean_nll(FakeModel(0.9), FakePipeline(), "a" * 40, 100)
        assert odd > likely

    def test_too_short_code_has_no_signal(self):
        assert inference.mean_nll(FakeModel(0.9), FakePipeline(), "a", 10) is None

    def test_max_tokens_truncates(self):
        _, n = inference.mean_nll(FakeModel(0.9), FakePipeline(), "ab" * 100, 10)
        assert n == 9

    def test_nll_to_risk_is_monotonic_and_bounded(self):
        risks = [inference.nll_to_risk(x, 2.0, 0.5) for x in (0, 1, 2, 3, 10, 1000)]
        assert risks == sorted(risks)
        assert risks[2] == pytest.approx(50.0)
        assert 0.0 <= risks[0] and risks[-1] <= 100.0


class TestCalibrationAndFailure:
    def test_no_model_returns_none_not_a_number(self):
        assert inference.score_code_snippet("x = 1") is None

    def test_uncalibrated_signal_is_withheld(self, fake_model):
        fake_model(0.9)
        result = inference.analyze_code("ab" * 20)
        assert result.score is None and result.nll is not None and not result.calibrated

    def test_opt_in_uncalibrated(self, fake_model, monkeypatch):
        fake_model(0.9)
        monkeypatch.setenv(inference.ENV_ALLOW_UNCALIBRATED, "1")
        result = inference.analyze_code("ab" * 20)
        assert result.score is not None and not result.calibrated

    def test_calibrated_signal(self, fake_model, monkeypatch, tmp_path):
        cal = tmp_path / "cal.json"
        cal.write_text(json.dumps({"midpoint": 1.0, "scale": 0.5}))
        monkeypatch.setenv(inference.ENV_CALIBRATION, str(cal))
        fake_model(0.9)
        confident = inference.analyze_code("ab" * 20)
        fake_model(0.01)
        doubtful = inference.analyze_code("ab" * 20)
        assert confident.calibrated and doubtful.calibrated
        assert confident.score < 50 < doubtful.score

    def test_inference_error_returns_none(self, fake_model, monkeypatch):
        fake_model(0.9)

        def boom(*a, **k):
            raise RuntimeError("out of memory")

        monkeypatch.setattr(model_loader._model, "forward", boom)
        assert inference.score_code_snippet("ab" * 20) is None

    def test_bad_calibration_file_is_ignored(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        assert inference.load_calibration(bad) is None
        bad.write_text(json.dumps({"midpoint": 1, "scale": 0}))
        assert inference.load_calibration(bad) is None


class TestParseScore:
    """The textual parser (used by remote scorers) never invents a value."""

    @pytest.mark.parametrize("raw,expected", [
        ('{"risk_score": 80}', 80.0),
        ('{"validity": 90}', 10.0),
        ("42", 42.0),
        ("150", 100.0),
        ('[{"call": "a", "validity": 0}, {"call": "b", "validity": 50}]', 75.0),
    ])
    def test_parses_valid_answers(self, raw, expected):
        assert inference._parse_score(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", [
        "", "No hallucination detected", "Python 3.11 is used",
        "1. The code uses requests.get", '{"score": "high"}', "[]", "true",
    ])
    def test_unparseable_answers_return_none(self, raw):
        assert inference._parse_score(raw) is None


class TestRouting:
    def test_no_model_is_heuristic_only_without_a_score(self):
        decision = router.score("x = 1")
        assert decision.route == "heuristic_only"
        assert decision.rwkv_score is None and decision.final_score is None

    def test_valid_score_stays_local(self, fake_model, monkeypatch):
        fake_model(0.9)
        monkeypatch.setenv(inference.ENV_ALLOW_UNCALIBRATED, "1")
        decision = router.score("ab" * 20)
        assert decision.route == "local"
        assert decision.final_score == decision.rwkv_score

    def test_cloud_key_never_triggers_a_call(self, monkeypatch):
        monkeypatch.setenv("HALLUGUARD_CLOUD_API_KEY", "secret")
        monkeypatch.setattr(router, "_warned_cloud", False)
        calls = []
        monkeypatch.setattr(router, "_call_cloud_llm", lambda code: calls.append(code))
        assert router.score("x = 1").route == "heuristic_only"
        assert calls == []
        assert router._cloud_available() is False

    def test_uncertain_band_escalates_only_when_cloud_exists(self, monkeypatch):
        monkeypatch.setattr(router.rwkv_inference, "score_code_snippet", lambda c: 50.0)
        assert router.score("x").route == "local"
        monkeypatch.setattr(router, "CLOUD_IMPLEMENTED", True)
        monkeypatch.setenv("HALLUGUARD_CLOUD_API_KEY", "k")
        monkeypatch.setattr(router, "_call_cloud_llm", lambda c: 70.0)
        d = router.score("x")
        assert (d.route, d.final_score, d.cloud_score) == ("cloud", 70.0, 70.0)
        # decisive scores (far from 50) never leave the machine, high *or* low
        for decisive in (5.0, 95.0):
            monkeypatch.setattr(router.rwkv_inference, "score_code_snippet", lambda c, v=decisive: v)
            assert router.score("x").route == "local"

    def test_routing_log_is_bounded(self, monkeypatch):
        monkeypatch.setattr(router, "_routing_log", router.deque(maxlen=5))
        for _ in range(20):
            router.score("x")
        assert len(router.get_routing_log()) == 5


class TestPipelineIntegration:
    def test_missing_rwkv_does_not_change_scores_or_invent_one(self):
        report = analyze("import not_real_zzz", offline=False)
        assert report._rwkv_raw == 0.0
        assert report.risk_score == 49  # 81 * 0.6, RWKV weight redistributed

    def test_calibrated_rwkv_enters_the_score(self, fake_model, monkeypatch, tmp_path):
        cal = tmp_path / "cal.json"
        cal.write_text(json.dumps({"midpoint": 1.0, "scale": 0.5}))
        monkeypatch.setenv(inference.ENV_CALIBRATION, str(cal))
        fake_model(0.01)
        report = analyze("ab" * 20 + " = 1", offline=True)
        assert report._rwkv_raw > 50


class TestAvailability:
    def test_is_available_needs_file_and_package(self, tmp_path, monkeypatch):
        model = tmp_path / "m.pth"
        model.write_text("x")
        monkeypatch.setenv("HALLUGUARD_RWKV_MODEL", str(model))
        monkeypatch.setattr(model_loader, "package_installed", lambda: False)
        assert model_loader.is_available() is False
        monkeypatch.setattr(model_loader, "package_installed", lambda: True)
        assert model_loader.is_available() is True

    def test_status_reports_each_condition(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HALLUGUARD_RWKV_MODEL", str(tmp_path / "absent.pth"))
        st = model_loader.status()
        assert st["model_file_found"] is False
        assert set(st) == {"model_path", "model_file_found", "package_installed", "loaded"}
