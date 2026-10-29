"""
Unit tests for core.verifier.npm_verifier
"""
from core.verifier.npm_verifier import check, check_package, is_node_builtin


class TestNodeBuiltins:
    """Test Node.js built-in detection."""

    def test_fs_is_builtin(self):
        assert is_node_builtin("fs") is True

    def test_path_is_builtin(self):
        assert is_node_builtin("path") is True

    def test_node_prefix(self):
        assert is_node_builtin("node:fs") is True

    def test_express_is_not_builtin(self):
        assert is_node_builtin("express") is False


class TestCheckPackage:
    """Test individual npm package verification (live API calls)."""

    def test_builtin(self):
        result = check_package("fs")
        assert result["exists"] is True
        assert result["type"] == "node_builtin"

    def test_real_package(self):
        result = check_package("express")
        assert result["exists"] is True
        assert result["type"] in ("npm_api", "npm_cached")

    def test_fake_package(self):
        result = check_package("totally-fake-nonexistent-pkg-xyz")
        assert result["exists"] is False

    def test_relative_import(self):
        result = check_package("./utils")
        assert result["exists"] is True
        assert result["type"] == "local"


class TestBatchCheck:
    """Test batch check on JS parser output."""

    def test_batch_check(self):
        tokens = {
            "imports": ["express"],
            "require_calls": ["axios", "nonexistent-fake-abc"],
        }
        result = check(tokens)
        vi = result["verified_imports"]
        assert vi["express"]["exists"] is True
        assert vi["axios"]["exists"] is True
        assert vi["nonexistent-fake-abc"]["exists"] is False
