"""
B6: attribute verification against the real, installed API.

Uses only modules that are always available (the standard library and
``requests``, a hard dependency of the project).
"""
from __future__ import annotations

import pytest

from core.pipeline import analyze
from core.verifier import api_checker


def _issues(code, **kw):
    report = analyze(code, **kw)
    return {h.token: h for h in report.hallucinations if h.issue_type == "unknown_attribute"}


class TestModuleAttributes:
    def test_hallucinated_method_on_real_package(self):
        found = _issues("import requests\nr = requests.fetch_json('http://x')\n")
        assert set(found) == {"requests.fetch_json"}
        issue = found["requests.fetch_json"]
        assert issue.severity == "HIGH"
        assert (issue.line, issue.column) == (2, 4)

    def test_real_attributes_pass(self):
        assert _issues("import requests\nrequests.get('u')\nrequests.post('u')\n") == {}

    def test_did_you_mean(self):
        found = _issues("import requests\nrequests.get_all('u')\n")
        assert found["requests.get_all"].suggestion == "Did you mean 'requests.get'?"

    def test_aliases(self):
        found = _issues("import os.path as op\nop.joinn('a')\nop.join('a')\n")
        assert set(found) == {"op.joinn"}

    def test_from_import_alias_of_module(self):
        found = _issues("from os import path as p\np.joinn('a')\np.join('a')\n")
        assert set(found) == {"p.joinn"}

    def test_submodule_access(self):
        code = "import collections.abc\ncollections.abc.Mapping()\ncollections.abc.Nope()\n"
        assert set(_issues(code)) == {"collections.abc.Nope"}

    def test_module_level_getattr_is_not_a_certain_miss(self):
        # concurrent.futures resolves some names lazily through __getattr__
        code = "import concurrent.futures\nconcurrent.futures.Nope()\n"
        assert _issues(code) == {}

    def test_nested_chain(self):
        found = _issues("import os\nos.path.joinn('a')\nos.path.join('a')\n")
        assert set(found) == {"os.path.joinn"}


class TestInstances:
    def test_attribute_on_instance_of_class_created_in_file(self):
        code = ("import collections\nd = collections.OrderedDict()\n"
                "d.move_to_end('a')\nd.magic_op()\n")
        found = _issues(code)
        assert set(found) == {"d.magic_op"}
        assert found["d.magic_op"].severity == "MEDIUM"  # instance: lower certainty

    def test_result_of_plain_function_is_not_inferred(self):
        code = "import logging\nlog = logging.getLogger('x')\nlog.infoo('bad')\n"
        report = analyze(code)
        assert report.hallucinations == []
        assert report.unverified == []

    def test_ambiguous_variable_is_skipped(self):
        code = ("import collections, threading\nx = collections.OrderedDict()\n"
                "x = threading.Thread()\nx.whatever()\n")
        assert _issues(code) == {}


class TestSafety:
    def test_uninstalled_package_is_not_checked(self):
        report = analyze("import fake_pkg_zzz as f\nf.run()\n", offline=True)
        assert not any(h.issue_type == "unknown_attribute" for h in report.hallucinations)

    def test_disabled_by_flag_and_env(self, monkeypatch):
        code = "import requests\nrequests.fetch_json('u')\n"
        assert _issues(code, check_attributes=False) == {}
        monkeypatch.setenv("HALLUGUARD_ATTR_CHECK", "0")
        assert _issues(code) == {}

    def test_import_with_side_effects_is_refused(self):
        assert api_checker.build_queries(
            {"aliases": {"antigravity": "antigravity"},
             "method_call_locations": [{"name": "antigravity.geohash", "line": 1, "col": 0}]}
        ) == {}

    def test_crashing_module_does_not_crash_analysis(self, tmp_path, monkeypatch):
        # A module that raises at import time must yield "unknown", not an error.
        (tmp_path / "explodes.py").write_text("raise RuntimeError('boom')\n")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv("PYTHONPATH", str(tmp_path))
        res = api_checker._run_child("explodes", False, ["x"])
        assert res["x"].status == "unknown"

    @pytest.mark.parametrize("flag", [True, False])
    def test_local_module_is_never_imported(self, flag, tmp_path):
        (tmp_path / "mine.py").write_text("raise SystemExit(3)\n")
        report = analyze("import mine\nmine.go()\n", project_root=str(tmp_path),
                         check_attributes=flag)
        assert report.hallucinations == []


class TestDynamicClasses:
    """Classes with __getattr__ accept any name: only an explicit allow-list is judged."""

    CODE = ("from xmlrpc.client import ServerProxy\n"
            "p = ServerProxy('http://localhost')\np.any_remote_method()\n")

    def test_dynamic_receivers_are_not_flagged_by_default(self):
        assert _issues(self.CODE) == {}

    def test_allow_listed_dynamic_class_is_flagged_as_medium(self, monkeypatch):
        monkeypatch.setattr(
            api_checker, "FLAGGABLE_DYNAMIC_CLASSES", frozenset({"xmlrpc.client.ServerProxy"})
        )
        found = _issues(self.CODE)
        assert set(found) == {"p.any_remote_method"}
        assert found["p.any_remote_method"].severity == "MEDIUM"

    def test_pandas_dataframe_is_allow_listed(self):
        assert "pandas.DataFrame" in api_checker.FLAGGABLE_DYNAMIC_CLASSES
