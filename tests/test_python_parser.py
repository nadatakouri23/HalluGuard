"""
Unit tests for core.parser.python_parser
"""
import pytest

from core.parser.python_parser import extract


class TestBasicImports:
    """Test extraction of import statements."""

    def test_simple_import(self):
        code = "import requests"
        result = extract(code, "python")
        assert "requests" in result["imports"]

    def test_multiple_imports(self):
        code = "import os\nimport sys\nimport json"
        result = extract(code, "python")
        assert set(result["imports"]) == {"os", "sys", "json"}

    def test_dotted_import(self):
        code = "import os.path"
        result = extract(code, "python")
        assert "os" in result["imports"]

    def test_from_import(self):
        code = "from os.path import join, exists"
        result = extract(code, "python")
        assert "os" in result["imports"]
        assert len(result["from_imports"]) == 1
        fi = result["from_imports"][0]
        assert fi["module"] == "os.path"

    def test_aliased_import(self):
        code = "import numpy as np"
        result = extract(code, "python")
        assert "numpy" in result["imports"]

    def test_from_import_alias(self):
        code = "from collections import OrderedDict as OD"
        result = extract(code, "python")
        assert "collections" in result["imports"]


class TestFunctionCalls:
    """Test extraction of function and method calls."""

    def test_bare_function_call(self):
        code = "print('hello')"
        result = extract(code, "python")
        assert "print" in result["function_calls"]

    def test_method_call(self):
        code = "requests.get('https://example.com')"
        result = extract(code, "python")
        assert "requests.get" in result["method_calls"]

    def test_nested_calls(self):
        code = "print(len(my_list))"
        result = extract(code, "python")
        assert "print" in result["function_calls"]
        assert "len" in result["function_calls"]

    def test_chained_method_call(self):
        code = "response.json().get('key')"
        result = extract(code, "python")
        # At least the top-level attribute call should be captured
        assert len(result["method_calls"]) >= 1


class TestDecoratorsAndAsync:
    """Test extraction of decorators, async functions, and classes."""

    def test_decorator_extraction(self):
        code = "@staticmethod\ndef my_func():\n    pass"
        result = extract(code, "python")
        assert "staticmethod" in result["decorators"]

    def test_decorator_with_args(self):
        code = "@app.route('/home')\ndef index():\n    pass"
        result = extract(code, "python")
        assert any("app.route" in d for d in result["decorators"])

    def test_class_extraction(self):
        code = "class MyService:\n    pass"
        result = extract(code, "python")
        assert "MyService" in result["classes"]

    def test_multiple_classes(self):
        code = "class A:\n    pass\n\nclass B:\n    pass"
        result = extract(code, "python")
        assert "A" in result["classes"]
        assert "B" in result["classes"]


class TestEdgeCases:
    """Test edge cases and complex patterns."""

    def test_empty_code(self):
        result = extract("", "python")
        assert result["imports"] == []
        assert result["function_calls"] == []

    def test_comment_only(self):
        result = extract("# just a comment", "python")
        assert result["imports"] == []

    def test_wrong_language_raises(self):
        with pytest.raises(ValueError):
            extract("code", "ruby")

    def test_complex_snippet(self):
        code = """
import requests
from bs4 import BeautifulSoup
import json

class Scraper:
    def fetch(self, url):
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        data = json.loads(response.text)
        return data
"""
        result = extract(code, "python")
        assert "requests" in result["imports"]
        assert "bs4" in result["imports"]
        assert "json" in result["imports"]
        assert "Scraper" in result["classes"]
        assert "requests.get" in result["method_calls"]
        assert "json.loads" in result["method_calls"]
