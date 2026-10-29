"""
Regression tests for the parsers: B2 (byte offsets), B3 (positions),
B5 (relative imports), B7 (scope), B18 (async).
"""
from __future__ import annotations

from core.parser import js_parser, python_parser


class TestUnicodeOffsets:
    """B2: tree-sitter gives byte offsets; slicing a str by them corrupts tokens."""

    def test_python_calls_after_non_ascii_comment(self):
        r = python_parser.extract("# é\nfoo(1)\nbar()\n")
        assert r["function_calls"] == ["foo", "bar"]

    def test_python_emoji_and_cjk(self):
        r = python_parser.extract('s = "😀 日本語"\nrequests.get(s)\nbaz()\n')
        assert "requests.get" in r["method_calls"]
        assert "baz" in r["function_calls"]

    def test_js_calls_after_non_ascii_comment(self):
        r = js_parser.extract("// é é\nfoo(1);\nbar();\naxios.get('x');\n")
        assert r["function_calls"] == ["foo", "bar"]
        assert r["method_calls"] == ["axios.get"]

    def test_js_module_specifier_after_non_ascii(self):
        r = js_parser.extract("const s = 'é';\nimport x from 'lodash';\n")
        assert r["imports"] == ["lodash"]


class TestPositions:
    """B3: every occurrence carries {name, line, col}."""

    def test_python_call_positions(self):
        r = python_parser.extract("import os\n\nfoo()\n    \nbar.baz()\n")
        assert r["function_call_locations"] == [{"name": "foo", "line": 3, "col": 0}]
        assert r["method_call_locations"] == [{"name": "bar.baz", "line": 5, "col": 0}]
        assert r["import_locations"] == [{"name": "os", "line": 1, "col": 7}]

    def test_column_counts_characters_not_bytes(self):
        r = python_parser.extract("é = foo()\n")
        assert r["function_call_locations"][0]["col"] == 4

    def test_js_positions(self):
        r = js_parser.extract("\nconst a = require('axios');\nfoo();\n")
        assert {"name": "axios", "line": 2, "col": 18} in r["import_locations"]
        assert r["function_call_locations"] == [{"name": "foo", "line": 3, "col": 0}]


class TestRelativeImports:
    """B5: relative imports are not registry packages."""

    def test_relative_imports_excluded_from_imports(self):
        r = python_parser.extract("from . import utils\nfrom .models import User\nfrom ..core import x\n")
        assert r["imports"] == []
        assert [i["module"] for i in r["relative_imports"]] == [".", ".models", "..core"]
        assert r["relative_imports"][1]["names"] == ["User"]
        assert {"utils", "User", "x"} <= set(r["defined_names"])

    def test_absolute_from_import_unchanged(self):
        r = python_parser.extract("from os.path import join\n")
        assert r["imports"] == ["os"]
        assert r["from_imports"][0]["module"] == "os.path"


class TestScope:
    """B7: names defined or bound in the file are known."""

    def test_definitions_parameters_and_targets(self):
        code = (
            "def f(a, b=1, *c, d: int = 2, **k):\n    pass\n"
            "class K:\n    pass\n"
            "for i, (x, y) in z:\n    pass\n"
            "with open(p) as fh, g() as (q, r):\n    pass\n"
            "try:\n    pass\nexcept E as err:\n    pass\n"
            "lam = lambda m, n=3: 0\n"
            "if (w := 3):\n    pass\n"
            "first, *rest = items\n"
        )
        defined = set(python_parser.extract(code)["defined_names"])
        assert {"f", "a", "b", "c", "d", "k", "K", "i", "x", "y", "fh", "q", "r",
                "err", "lam", "m", "n", "w", "first", "rest"} <= defined

    def test_attribute_targets_bind_nothing(self):
        defined = python_parser.extract("self.x = 1\nobj.y = 2\n")["defined_names"]
        assert "x" not in defined and "y" not in defined

    def test_aliases(self):
        r = python_parser.extract(
            "import numpy as np\nimport os.path as op\nimport json\n"
            "from collections import OrderedDict as OD\nfrom z import q as r\n"
        )
        assert r["aliases"]["np"] == "numpy"
        assert r["aliases"]["op"] == "os.path"
        assert r["aliases"]["json"] == "json"
        assert r["aliases"]["OD"] == "collections.OrderedDict"
        assert r["aliases"]["r"] == "z.q"
        assert r["from_imports"][-1]["names"] == ["q"]  # was [] before

    def test_star_imports_recorded(self):
        assert python_parser.extract("from os import *\n")["star_imports"] == ["os"]

    def test_single_assignment_callee_recorded(self):
        r = python_parser.extract("import pandas as pd\ndf = pd.DataFrame()\n")
        assert r["assignments"] == {"df": ["pd.DataFrame"]}

    def test_js_scope(self):
        code = (
            "import d, {a, b as c} from 'm';\nimport * as ns from 'n';\n"
            "const {p, q: r} = require('x');\nfunction f(x, y = 2, ...z) {}\n"
            "const g = (u, {v}) => u;\nconst h = w => w;\nclass K {}\n"
            "try {} catch (err) {}\nfor (const i of items) {}\n"
        )
        r = js_parser.extract(code)
        assert {"d", "a", "c", "ns", "p", "r", "f", "x", "y", "z", "g", "u", "v",
                "h", "w", "K", "err", "i"} <= set(r["defined_names"])
        assert "b" not in r["defined_names"]  # only the alias is bound

    def test_js_require_alias_and_dynamic_import(self):
        r = js_parser.extract("const ax = require('axios');\nimport('lazy');\n")
        assert r["aliases"]["ax"] == "axios"
        assert r["imports"] == ["lazy"]
        assert r["require_calls"] == ["axios"]

    def test_js_import_and_require_do_not_shadow_each_other(self):
        r = js_parser.extract("import a from 'dup';\nconst b = require('dup');\n")
        assert r["imports"] == ["dup"] and r["require_calls"] == ["dup"]


class TestAsync:
    """B18: async functions are detected."""

    def test_async_functions(self):
        r = python_parser.extract(
            "async def g():\n    pass\n\n@app.get('/x')\nasync def h():\n    await g()\n"
            "def plain():\n    pass\n"
        )
        assert r["async_functions"] == ["g", "h"]
        assert r["decorators"] == ["app.get"]
