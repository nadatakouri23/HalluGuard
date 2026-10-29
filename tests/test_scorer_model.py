"""
Regression tests for the scorer: B3 (lines), B7 (false positives),
B13 (severity/confidence), B14 (dilution/saturation).
"""
from __future__ import annotations

import pytest

from core.pipeline import analyze
from core.scorer.hallucination_scorer import _severity_label, compute


def _tokens(**kw):
    base = {"imports": [], "function_calls": [], "from_imports": []}
    base.update(kw)
    return base


class TestLineNumbers:
    """B3: issues carry the real line and column."""

    def test_issue_positions_from_parser(self):
        code = "import requests\nimport fake_pkg_zzz\n\nmystery_call(1)\n"
        report = analyze(code)
        by_token = {h.token: h for h in report.hallucinations}
        assert (by_token["fake_pkg_zzz"].line, by_token["fake_pkg_zzz"].column) == (2, 7)
        assert (by_token["mystery_call"].line, by_token["mystery_call"].column) == (4, 0)

    def test_json_exposes_column(self):
        d = analyze("nothing_here()").to_dict()
        assert d["hallucinations"][0]["line"] == 1
        assert d["hallucinations"][0]["column"] == 0

    def test_js_lines(self):
        report = analyze("const a = 1;\nfoo();\n", language="javascript")
        assert report.hallucinations[0].line == 2


class TestFalsePositives:
    """B7: only genuinely unresolved names are reported."""

    def test_builtins_are_known(self):
        code = ("print(bytes(1), bytearray(1), callable(len), format(1), ord('a'), "
                "chr(3), divmod(1, 2), pow(2, 3), frozenset(), object(), "
                "Exception('x'), ValueError('y'), slice(1), complex(1), bin(1), "
                "hex(1), __import__('os'))")
        assert analyze(code).hallucinations == []

    def test_local_definitions_and_aliases_are_known(self):
        code = (
            "from collections import OrderedDict as OD\nfrom z_unknown import q as r\n"
            "def helper(x):\n    return x\n"
            "class A:\n    def m(self):\n        return 1\n"
            "def main(callback):\n    helper(1)\n    A().m()\n    OD()\n    r()\n"
            "    callback(2)\n    k = lambda v: v\n    k(1)\n"
        )
        names = [h.token for h in analyze(code, offline=True).hallucinations]
        assert names == []

    def test_truly_unknown_call_is_still_reported(self):
        names = [h.token for h in analyze("mystery()\n").hallucinations]
        assert names == ["mystery"]

    def test_star_import_disables_function_check(self):
        assert analyze("from os import *\ngetcwd()\n", offline=True).hallucinations == []

    @pytest.mark.parametrize("name", ["fetch", "setTimeout", "parseInt", "Promise", "require"])
    def test_js_globals_are_known(self, name):
        assert analyze(f"{name}(1);", language="javascript").hallucinations == []

    def test_js_imported_and_local_names_are_known(self):
        code = ("import {useState} from 'react';\nfunction f() {}\n"
                "const g = () => 1;\nuseState(); f(); g();\n")
        assert analyze(code, language="javascript").hallucinations == []

    def test_python_builtins_do_not_leak_into_js(self):
        names = [h.token for h in analyze("len(x);", language="javascript").hallucinations]
        assert names == ["len"]


class TestSeverityAndConfidence:
    """B13: severity and confidence now mean something."""

    def test_clean_file_has_severity_none(self):
        report = analyze("import os\nprint(os.name)\n")
        assert report.severity == "NONE" and report.risk_level == "NONE"
        assert report.confidence == "HIGH"

    def test_severity_is_the_worst_issue(self):
        assert analyze("mystery()").severity == "MEDIUM"
        assert analyze("import not_real_zzz").severity == "HIGH"
        assert analyze("import not_real_zzz\nmystery()").severity == "HIGH"

    def test_severity_label_zero_is_none(self):
        assert [_severity_label(s) for s in (0, 1, 25, 26, 50, 51, 75, 76, 100)] == [
            "NONE", "LOW", "LOW", "MEDIUM", "MEDIUM", "HIGH", "HIGH", "CRITICAL", "CRITICAL",
        ]

    def test_confidence_reflects_verifiability(self, registry):
        assert analyze("import flask").confidence == "HIGH"
        registry.fail = True
        assert analyze("import numpy").confidence == "LOW"
        assert analyze("import os\nimport requests").confidence == "MEDIUM"

    def test_nothing_to_verify_is_low_confidence(self):
        assert analyze("x = 1\n").confidence == "LOW"

    def test_to_dict_exposes_new_fields(self):
        d = analyze("import not_real_zzz").to_dict()
        assert {"risk_level", "severity", "unverified", "notes"} <= set(d)


class TestScoreShape:
    """B14: no 100/N dilution, no hard saturation at 7 functions."""

    def _k(self, n_valid):
        names = ["fake"] + [f"ok{i}" for i in range(n_valid)]
        knowledge = {"verified_imports": {
            n: {"exists": n != "fake"} for n in names}}
        return compute(_tokens(imports=names), knowledge)

    def test_hallucinated_import_is_not_diluted_by_valid_ones(self):
        assert self._k(0).risk_score == self._k(19).risk_score > 40

    def test_more_unknown_functions_keep_increasing_the_score(self):
        scores = [
            compute(_tokens(function_calls=[f"f{i}" for i in range(n)]),
                    {"verified_imports": {}}).risk_score
            for n in (1, 3, 7, 14, 28)
        ]
        assert scores == sorted(scores)
        assert len(set(scores)) == len(scores)       # strictly increasing
        assert scores[2] < 100 and scores[-1] <= 100  # 7 calls != 100

    def test_two_fake_imports_worse_than_one(self):
        one = compute(_tokens(imports=["a"]), {"verified_imports": {"a": {"exists": False}}})
        two = compute(_tokens(imports=["a", "b"]), {"verified_imports": {
            "a": {"exists": False}, "b": {"exists": False}}})
        assert two.risk_score > one.risk_score

    def test_undetermined_import_adds_no_risk(self):
        report = compute(_tokens(imports=["a"]), {"verified_imports": {"a": {"exists": None}}})
        assert report.risk_score == 0 and report.unverified == ["a"]

    def test_rwkv_weight_is_redistributed_when_absent(self):
        k = {"verified_imports": {"a": {"exists": False}}}
        t = _tokens(imports=["a"])
        without = compute(t, k, rwkv_score=None)
        with_zero = compute(t, k, rwkv_score=0.0)
        assert without.risk_score > with_zero.risk_score  # weight 0.6 vs 0.5
        assert compute(t, k, rwkv_score=-1.0).risk_score == without.risk_score
