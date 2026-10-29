"""
Unit tests for core.verifier.pypi_verifier
"""
from core.verifier.pypi_verifier import check, check_package, is_standard_library


class TestStdlibDetection:
    """Test standard library detection."""

    def test_os_is_stdlib(self):
        assert is_standard_library("os") is True

    def test_sys_is_stdlib(self):
        assert is_standard_library("sys") is True

    def test_json_is_stdlib(self):
        assert is_standard_library("json") is True

    def test_requests_is_not_stdlib(self):
        assert is_standard_library("requests") is False

    def test_fake_is_not_stdlib(self):
        assert is_standard_library("totally_fake_pkg") is False


class TestCheckPackage:
    """Test individual package verification (live API calls)."""

    def test_stdlib_package(self):
        result = check_package("os")
        assert result["exists"] is True
        assert result["type"] == "stdlib"

    def test_real_package(self):
        result = check_package("requests")
        assert result["exists"] is True
        assert result["type"] in ("pypi_api", "pypi_cached")

    def test_fake_package(self):
        result = check_package("this_package_definitely_does_not_exist_xyz123")
        assert result["exists"] is False

    def test_cache_hit(self):
        """Second call for the same package should hit cache."""
        check_package("requests")  # prime cache
        result = check_package("requests")
        assert result["exists"] is True
        assert result["type"] == "pypi_cached"


class TestBatchCheck:
    """Test batch check on parser output."""

    def test_batch_check(self):
        tokens = {"imports": ["os", "requests", "nonexistent_pkg_abc"]}
        result = check(tokens)
        vi = result["verified_imports"]
        assert vi["os"]["exists"] is True
        assert vi["requests"]["exists"] is True
        assert vi["nonexistent_pkg_abc"]["exists"] is False
