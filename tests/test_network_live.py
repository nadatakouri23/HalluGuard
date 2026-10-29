"""
Live checks against the real PyPI / npm registries.

Skipped unless ``HALLUGUARD_TEST_NETWORK=1`` (they depend on the Internet and
are therefore not part of the default, deterministic test run).
"""
import pytest

from core.verifier.npm_verifier import check_package as npm_check
from core.verifier.pypi_verifier import check_package as pypi_check

pytestmark = pytest.mark.network


def test_pypi_real_and_fake():
    real = pypi_check("requests")
    assert real["exists"] in (True, None)  # None = transient network failure
    fake = pypi_check("this_package_definitely_does_not_exist_xyz123")
    assert fake["exists"] in (False, None)


def test_pypi_import_name_mapping_uses_distribution():
    assert pypi_check("yaml")["exists"] is True


def test_npm_real_and_fake():
    assert npm_check("axios")["exists"] in (True, None)
    assert npm_check("nonexistent-fake-abc-xyz-123")["exists"] in (False, None)
