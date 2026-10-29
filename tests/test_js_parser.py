"""
Unit tests for core.parser.js_parser
"""
import pytest

from core.parser.js_parser import extract


class TestES6Imports:
    """Test extraction of ES6 import statements."""

    def test_default_import(self):
        code = "import express from 'express';"
        result = extract(code, "javascript")
        assert "express" in result["imports"]

    def test_named_import(self):
        code = "import { useState, useEffect } from 'react';"
        result = extract(code, "javascript")
        assert "react" in result["imports"]

    def test_scoped_import(self):
        code = "import something from '@scope/package';"
        result = extract(code, "javascript")
        assert "@scope/package" in result["imports"]


class TestRequireCalls:
    """Test extraction of CommonJS require()."""

    def test_basic_require(self):
        code = "const axios = require('axios');"
        result = extract(code, "javascript")
        assert "axios" in result["require_calls"]

    def test_require_scoped(self):
        code = "const core = require('@actions/core');"
        result = extract(code, "javascript")
        assert "@actions/core" in result["require_calls"]


class TestMethodCalls:
    """Test extraction of method and function calls."""

    def test_method_call(self):
        code = "axios.get('/api/users');"
        result = extract(code, "javascript")
        assert "axios.get" in result["method_calls"]

    def test_console_log(self):
        code = "console.log('hello');"
        result = extract(code, "javascript")
        assert "console.log" in result["method_calls"]

    def test_fetch_detection(self):
        code = "fetch('https://api.example.com/data');"
        result = extract(code, "javascript")
        assert "fetch" in result["function_calls"]
        assert len(result["fetch_calls"]) >= 1


class TestTypeScript:
    """Test TypeScript parsing."""

    def test_ts_import(self):
        code = "import { Router } from 'express';"
        result = extract(code, "typescript")
        assert "express" in result["imports"]

    def test_ts_method(self):
        code = "console.log('ts test');"
        result = extract(code, "typescript")
        assert "console.log" in result["method_calls"]


class TestEdgeCases:
    """Edge cases for the JS/TS parser."""

    def test_empty_code(self):
        result = extract("", "javascript")
        assert result["imports"] == []
        assert result["function_calls"] == []

    def test_unsupported_language(self):
        with pytest.raises(ValueError):
            extract("code", "rust")
