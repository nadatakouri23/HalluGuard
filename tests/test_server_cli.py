"""
B8 (CLI entry point), B15 (corrector), B16 (API), B20 (health).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from cli import analyzer as cli
from core.corrector.suggestion_engine import suggest
from core.pipeline import analyze
from core.scorer.hallucination_scorer import HallucinationIssue, HallucinationReport

FIXTURES = Path(__file__).parent / "fixtures"


def _report(issue_type, token, suggestion=""):
    return HallucinationReport(hallucinations=[HallucinationIssue(
        line=1, issue_type=issue_type, token=token, explanation="x",
        suggestion=suggestion, severity="HIGH")])


# ── B15: corrector ─────────────────────────────────────────────────
class TestCorrector:
    @pytest.mark.parametrize("name", ["object", "slice", "Exception", "list"])
    def test_no_absurd_function_suggestions(self, name):
        (s,) = suggest(_report("unknown_function", name), language="python")
        assert s["suggestion"] is None and s["confidence"] == "LOW"

    def test_py_alias_uses_python_candidates(self):
        (s,) = suggest(_report("unknown_import", "reqeusts"), language="py")
        assert s["suggestion"] == "requests"
        (s,) = suggest(_report("unknown_import", "expres"), language="js")
        assert s["suggestion"] == "express"

    @pytest.mark.parametrize("language", ["python", "py", "PY", "Python"])
    def test_language_aliases_equivalent(self, language):
        (s,) = suggest(_report("unknown_import", "reqeusts"), language=language)
        assert s["suggestion"] == "requests"

    @pytest.mark.parametrize("token", ["utils", "helpers", "zzz", "User"])
    def test_weak_matches_are_not_suggested(self, token):
        (s,) = suggest(_report("unknown_import", token), language="python")
        assert s["suggestion"] is None

    def test_valid_packages_are_never_proposed_as_fixes_for_themselves(self):
        (s,) = suggest(_report("unknown_import", "numpy"), language="python")
        assert s["suggestion"] != "numpy"  # used to answer "Did you mean 'numpy'?"

    def test_hallucinated_function_is_language_specific(self):
        (py,) = suggest(_report("unknown_function", "fetchUserData"), language="python")
        (js,) = suggest(_report("unknown_function", "fetchUserData"), language="javascript")
        assert "requests" in py["suggestion"] and "requests" not in js["suggestion"]

    def test_attribute_suggestion_comes_from_the_real_api(self):
        report = analyze("import requests\nrequests.get_all('u')\n")
        (s,) = [x for x in report.suggestions if x["token"] == "requests.get_all"]
        assert s["suggestion"] == "requests.get" and s["confidence"] == "MEDIUM"

    def test_wrong_import_name_gets_high_confidence_fix(self):
        report = analyze("import pillow\n")
        assert report.suggestions[0]["suggestion"] == "PIL"
        assert report.suggestions[0]["confidence"] == "HIGH"


# ── B8: CLI ────────────────────────────────────────────────────────
class TestCli:
    def test_main_is_a_console_entry_point(self):
        assert callable(cli.main)
        toml = (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        assert 'halluguard = "cli.analyzer:main"' in toml

    def test_runs_and_prints_only_json(self, capsys):
        rc = cli.main([str(FIXTURES / "hallucinated_code.py"), "--offline"])
        out = capsys.readouterr().out
        reports = json.loads(out)
        assert rc == 0 and reports[0]["file"].endswith("hallucinated_code.py")

    def test_fail_on_threshold(self, capsys, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("import not_real_zzz\n")
        assert cli.main([str(bad), "--fail-on", "HIGH"]) == 1
        ok = tmp_path / "ok.py"
        ok.write_text("import os\nprint(os.name)\n")
        assert cli.main([str(ok), "--fail-on", "LOW"]) == 0

    def test_unsupported_and_missing_files_are_skipped(self, capsys, tmp_path):
        txt = tmp_path / "notes.txt"
        txt.write_text("x")
        cli.main([str(txt), str(tmp_path / "nope.py")])
        captured = capsys.readouterr()
        assert json.loads(captured.out) == []
        assert "nope.py" in captured.err

    def test_latin1_file_does_not_crash(self, capsys, tmp_path):
        f = tmp_path / "latin.py"
        f.write_bytes("# caf\xe9\nimport os\n".encode("latin-1"))
        cli.main([str(f), "--offline"])
        assert json.loads(capsys.readouterr().out)[0]["file"].endswith("latin.py")

    def test_python_dash_m_cli_analyzer(self, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("import os\n")
        proc = subprocess.run(
            [sys.executable, "-m", "cli.analyzer", "--offline", str(f)],
            capture_output=True, text=True, cwd=Path(__file__).parents[1], check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)[0]["severity"] == "NONE"

    def test_fixture_files_end_to_end(self):
        code = (FIXTURES / "sklearn_snippet.py").read_text(encoding="utf-8")
        report = analyze(code, offline=True)
        # sklearn/requests/pandas are valid imports; the undefined `df` is not a *call*
        assert not any(h.issue_type == "unknown_import" for h in report.hallucinations)


# ── B16 / B20: API ─────────────────────────────────────────────────
class TestApi:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from api.server import app
        return TestClient(app)

    def test_analyze(self, client):
        r = client.post("/analyze", json={"code": "import not_real_zzz\n"})
        assert r.status_code == 200
        body = r.json()
        assert body["severity"] == "HIGH"
        assert body["hallucinations"][0]["line"] == 1
        assert {"risk_level", "unverified", "notes"} <= set(body)

    def test_unsupported_language_is_a_client_error_not_500(self, client):
        r = client.post("/analyze", json={"code": "x", "language": "rust"})
        assert r.status_code == 400
        assert "Unsupported language" in r.json()["detail"]

    def test_language_aliases(self, client):
        r = client.post("/analyze", json={"code": "foo();", "language": "JS"})
        assert r.status_code == 200 and r.json()["file"] == "snippet.js"

    def test_offline_flag(self, client, registry):
        client.post("/analyze", json={"code": "import mystery_pkg", "offline": True})
        assert registry.calls == []

    def test_health_details(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert {"rwkv_available", "rwkv_model_file_found",
                "rwkv_package_installed", "rwkv_loaded"} <= set(body)

    def test_cors_is_off_by_default(self, client):
        r = client.post(
            "/analyze", json={"code": "x = 1"},
            headers={"Origin": "https://evil.example"},
        )
        assert "access-control-allow-origin" not in r.headers

    def test_endpoints_do_not_block_the_event_loop(self):
        import inspect

        from api import server
        assert not inspect.iscoroutinefunction(server.analyze_code)
        assert not inspect.iscoroutinefunction(server.health_check)

    def test_wildcard_origin_is_never_honoured(self, monkeypatch):
        import importlib

        from api import server
        monkeypatch.setenv("HALLUGUARD_CORS_ORIGINS", "*")
        reloaded = importlib.reload(server)
        try:
            assert reloaded._origins == []
        finally:
            monkeypatch.delenv("HALLUGUARD_CORS_ORIGINS")
            importlib.reload(server)


class TestTextFormat:
    def test_text_output_is_one_line_per_finding(self, capsys, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("import os\nmystery()\n")
        rc = cli.main([str(f), "--offline", "--format", "text"])
        lines = capsys.readouterr().out.strip().splitlines()
        assert rc == 0
        assert lines[0].endswith("unknown_function mystery - Function 'mystery()' is not a known builtin, definition or import.")
        assert ":2:0: MEDIUM " in lines[0]
        assert "severity=MEDIUM" in lines[-1]
