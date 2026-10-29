"""
Shared test fixtures.

Every test runs against a **fake package registry**: results no longer depend
on the Internet (a timeout used to turn into "package does not exist").
Tests marked ``network`` use the real registries and only run when
``HALLUGUARD_TEST_NETWORK=1``.
"""
from __future__ import annotations

import os
import urllib.parse
from typing import Any

import pytest

from core.verifier import api_checker, common, npm_verifier, pypi_verifier

PYPI_PACKAGES = {
    "requests", "numpy", "pandas", "flask", "beautifulsoup4", "scikit-learn",
    "opencv-python", "pyyaml", "pillow", "python-dateutil",
}
NPM_PACKAGES = {"express", "axios", "react", "lodash", "@actions/core"}


class FakeRegistry:
    """Controllable stand-in for PyPI and npm."""

    def __init__(self) -> None:
        self.pypi: set[str] = set(PYPI_PACKAGES)
        self.npm: set[str] = set(NPM_PACKAGES)
        self.fail = False          # simulate a network failure
        self.calls: list[str] = []
        self.pypi_docs: dict[str, dict[str, Any]] = {}

    def get(self, url: str, **_: Any) -> common.Lookup:
        self.calls.append(url)
        if self.fail:
            return common.Lookup("error", error="simulated network failure")
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc == "pypi.org":
            name = parsed.path.split("/")[2]
            if name not in self.pypi:
                return common.Lookup("missing")
            doc = self.pypi_docs.get(name) or {
                "info": {"version": "1.0.0", "summary": "A package",
                         "classifiers": []},
                "releases": {
                    "1.0.0": [{"upload_time_iso_8601": "2015-01-01T00:00:00Z"}],
                    "1.1.0": [{"upload_time_iso_8601": "2016-01-01T00:00:00Z"}],
                },
            }
            return common.Lookup("found", data=doc)
        name = urllib.parse.unquote(parsed.path.lstrip("/"))
        if name not in self.npm:
            return common.Lookup("missing")
        return common.Lookup("found", data={
            "dist-tags": {"latest": "1.0.0"}, "versions": {"1.0.0": {}, "1.1.0": {}},
        })


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "network: uses the real PyPI/npm registries")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if os.environ.get("HALLUGUARD_TEST_NETWORK") == "1":
        return
    skip = pytest.mark.skip(reason="set HALLUGUARD_TEST_NETWORK=1 to run live tests")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def registry(
    request: pytest.FixtureRequest,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> FakeRegistry:
    """Isolate caches/env and route registry traffic to a fake."""
    monkeypatch.setenv("HALLUGUARD_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("HALLUGUARD_IGNORE_INSTALLED", "1")
    monkeypatch.delenv("HALLUGUARD_OFFLINE", raising=False)
    monkeypatch.delenv("HALLUGUARD_ATTR_CHECK", raising=False)
    pypi_verifier.clear_cache()
    npm_verifier.clear_cache()
    api_checker.clear_cache()

    fake = FakeRegistry()
    if "network" in request.keywords:
        monkeypatch.delenv("HALLUGUARD_IGNORE_INSTALLED", raising=False)
    else:
        monkeypatch.setattr(common, "http_get_json", fake.get)
    return fake
