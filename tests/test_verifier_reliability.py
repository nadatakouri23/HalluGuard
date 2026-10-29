"""
Regression tests for the verifiers: B1 (tri-state/retry), B4 (import mapping),
B5 (local modules), B12 (cache/offline/parallel), B17 (squatting signals),
B24 (stdlib / Node built-ins).
"""
from __future__ import annotations

import pytest
import requests

from core.pipeline import analyze
from core.verifier import common, npm_verifier, pypi_verifier

_real_http_get_json = common.http_get_json  # captured before the autouse fake


# ── B1: a network failure is "undetermined", never "does not exist" ──
class TestTriState:
    def test_network_error_is_undetermined(self, registry):
        registry.fail = True
        result = pypi_verifier.check_package("requests")
        assert result["exists"] is None
        assert result["type"] == "unverified"
        assert "error" in result

    def test_network_error_flags_nothing(self, registry):
        registry.fail = True
        report = analyze("import requests\nimport numpy", language="python")
        assert report.hallucinations == []
        assert set(report.unverified) == {"requests", "numpy"}
        assert report.confidence != "HIGH"
        assert any("could not be verified" in n for n in report.notes)

    def test_network_error_is_not_cached(self, registry):
        registry.fail = True
        pypi_verifier.check_package("requests")
        registry.fail = False
        assert pypi_verifier.check_package("requests")["exists"] is True

    def test_npm_network_error_is_undetermined(self, registry):
        registry.fail = True
        assert npm_verifier.check_package("express")["exists"] is None
        report = analyze("import express from 'express';", language="javascript")
        assert report.hallucinations == []
        assert report.unverified == ["express"]

    def test_real_miss_is_still_reported(self):
        report = analyze("import totally_fake_pkg_zzz", language="python")
        assert [h.token for h in report.hallucinations] == ["totally_fake_pkg_zzz"]
        assert report.severity == "HIGH"


class TestRetry:
    def _patch(self, monkeypatch, statuses):
        calls = []

        class Resp:
            def __init__(self, code):
                self.status_code = code

            def json(self):
                return {"ok": True}

        def fake_get(url, **kwargs):
            code = statuses[min(len(calls), len(statuses) - 1)]
            calls.append(code)
            if code == "timeout":
                raise requests.ReadTimeout("slow")
            return Resp(code)

        monkeypatch.setattr(common.requests, "get", fake_get)
        monkeypatch.setattr(common.time, "sleep", lambda s: None)
        return calls

    def test_retries_on_timeout_then_succeeds(self, monkeypatch):
        calls = self._patch(monkeypatch, ["timeout", 503, 200])
        assert _real_http_get_json("https://x").state == "found"
        assert len(calls) == 3

    def test_gives_up_with_error_not_missing(self, monkeypatch):
        self._patch(monkeypatch, ["timeout"])
        assert _real_http_get_json("https://x").state == "error"

    def test_404_is_missing_without_retry(self, monkeypatch):
        calls = self._patch(monkeypatch, [404])
        assert _real_http_get_json("https://x").state == "missing"
        assert len(calls) == 1

    def test_403_is_error_without_retry(self, monkeypatch):
        calls = self._patch(monkeypatch, [403])
        assert _real_http_get_json("https://x").state == "error"
        assert len(calls) == 1


# ── B4: import name != distribution name ───────────────────────────
class TestImportMapping:
    @pytest.mark.parametrize("imp", ["cv2", "yaml", "PIL", "sklearn", "bs4", "dateutil"])
    def test_valid_import_names_are_not_flagged(self, imp, registry):
        report = analyze(f"import {imp}", language="python")
        assert report.hallucinations == []
        assert registry.calls == []  # curated mapping: no lookup needed

    def test_distribution_name_used_as_import_is_flagged(self):
        report = analyze("import pillow\nimport beautifulsoup", language="python")
        assert {h.token for h in report.hallucinations} == {"pillow", "beautifulsoup"}
        pillow = next(h for h in report.hallucinations if h.token == "pillow")
        assert "PIL" in pillow.explanation
        fixes = {s["token"]: s["suggestion"] for s in report.suggestions}
        assert fixes["pillow"] == "PIL"

    def test_pypi_is_queried_by_normalised_distribution_name(self, registry):
        pypi_verifier.check_package("Some_Pkg.Name")
        assert registry.calls[-1] == "https://pypi.org/pypi/some-pkg-name/json"


# ── B5: relative and local imports ─────────────────────────────────
class TestLocalImports:
    def test_relative_imports_are_never_looked_up(self, registry):
        code = "from . import utils\nfrom .models import User\nfrom ..core import x\n"
        report = analyze(code, language="python")
        assert report.hallucinations == []
        assert registry.calls == []

    def test_local_module_next_to_file_is_resolved(self, tmp_path, registry):
        (tmp_path / "pyproject.toml").write_text("")
        (tmp_path / "helpers.py").write_text("def f(): ...\n")
        (tmp_path / "pkg").mkdir()
        main = tmp_path / "main.py"
        main.write_text("import helpers\nimport pkg\n")
        report = analyze(main.read_text(), file_name=str(main))
        assert report.hallucinations == []
        assert registry.calls == []

    def test_project_root_option(self, tmp_path):
        (tmp_path / "mylib").mkdir()
        report = analyze("import mylib", project_root=str(tmp_path))
        assert report.hallucinations == []

    def test_unresolvable_local_name_is_still_flagged(self, tmp_path):
        report = analyze("import ghost_module", project_root=str(tmp_path))
        assert [h.token for h in report.hallucinations] == ["ghost_module"]

    def test_npm_local_specifiers(self, registry):
        code = "import a from './a'; import b from '../b'; import c from '#internal/c';"
        report = analyze(code, language="javascript")
        assert report.hallucinations == []
        assert registry.calls == []


# ── B12: offline mode, disk cache, parallelism ─────────────────────
class TestPerformanceAndOffline:
    def test_offline_never_touches_the_network(self, registry):
        report = analyze("import requests\nimport mystery_pkg", offline=True)
        assert registry.calls == []
        assert report.hallucinations == []
        assert "mystery_pkg" in report.unverified
        assert any("offline" in n for n in report.notes)

    def test_offline_env_var(self, registry, monkeypatch):
        monkeypatch.setenv("HALLUGUARD_OFFLINE", "1")
        analyze("import mystery_pkg")
        assert registry.calls == []

    def test_offline_knows_popular_packages(self):
        result = pypi_verifier.check_package("flask", offline=True)
        assert result["exists"] is True and result["type"] == "known_offline"
        result = npm_verifier.check_package("express", offline=True)
        assert result["exists"] is True

    def test_disk_cache_survives_a_new_process(self, registry):
        pypi_verifier.check({"imports": ["flask"]})  # looks up, then flushes to disk
        n = len(registry.calls)
        pypi_verifier._cache.clear()       # simulate a fresh process...
        pypi_verifier._disk_cache.reset()  # ...that only has the disk file
        result = pypi_verifier.check_package("flask")
        assert result["type"] == "pypi_cached"
        assert len(registry.calls) == n

    def test_batch_checks_all_imports(self, registry):
        names = ["flask", "requests", "numpy", "pandas", "nope_a", "nope_b"]
        out = pypi_verifier.check({"imports": names})["verified_imports"]
        assert list(out) == names
        assert [out[n]["exists"] for n in names] == [True] * 4 + [False] * 2

    def test_npm_scoped_names_are_encoded(self, registry):
        npm_verifier.check_package("@actions/core")
        assert registry.calls[-1] == "https://registry.npmjs.org/@actions%2Fcore"


# ── B17: existence is not proof of legitimacy ──────────────────────
class TestSquattingSignals:
    def test_young_single_release_package_is_noted(self, registry):
        import time

        registry.pypi.add("freshpkg")
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5 * 86400))
        registry.pypi_docs["freshpkg"] = {
            "info": {"version": "0.0.1", "summary": "x", "classifiers": []},
            "releases": {"0.0.1": [{"upload_time_iso_8601": stamp}]},
        }
        report = analyze("import freshpkg")
        assert [(h.issue_type, h.severity) for h in report.hallucinations] == [
            ("suspicious_package", "LOW")
        ]

    def test_deprecated_package_is_noted(self, registry):
        registry.pypi.add("oldpkg")
        registry.pypi_docs["oldpkg"] = {
            "info": {"version": "1", "summary": "Deprecated: use newpkg", "classifiers": []},
            "releases": {"1": [{"upload_time_iso_8601": "2015-01-01T00:00:00Z"}]},
        }
        report = analyze("import oldpkg")
        assert [h.issue_type for h in report.hallucinations] == ["deprecated_package"]
        assert report.severity == "LOW"

    def test_mature_package_is_clean(self):
        assert analyze("import flask").hallucinations == []


# ── B24: standard library and Node built-ins ───────────────────────
class TestBuiltinsCoverage:
    @pytest.mark.parametrize("mod", ["distutils", "imp", "asyncore", "telnetlib"])
    def test_recently_removed_stdlib_is_accepted(self, mod):
        assert pypi_verifier.is_standard_library(mod)

    @pytest.mark.parametrize(
        "spec",
        ["async_hooks", "inspector", "diagnostics_channel", "trace_events",
         "node:test", "node:sqlite", "fs/promises", "node:fs/promises"],
    )
    def test_node_builtins(self, spec):
        result = npm_verifier.check_package(spec)
        assert result["exists"] is True and result["type"] == "node_builtin"

    def test_stdlib_set_is_not_limited_to_old_pythons(self):
        assert pypi_verifier.is_standard_library("tomllib")
