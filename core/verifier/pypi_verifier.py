"""
PyPI Knowledge Verifier.

For each absolute Python import, decides whether the module is real.
Resolution order for an import name:

1. standard library (current interpreter + recently removed modules);
2. project-local module (``utils.py`` / ``utils/`` next to the analysed file);
3. wrong-import-name table (``import pillow`` -> the module is ``PIL``);
4. module installed in the running environment;
5. curated import -> distribution mapping (``cv2`` -> ``opencv-python``);
6. offline: curated list of popular packages, otherwise *undetermined*;
7. cache (memory, then disk), then the live PyPI JSON API.

``exists`` is **tri-state**: ``True`` / ``False`` / ``None``.  ``None`` means
"could not be determined" (network failure, offline mode, HTTP 5xx...): the
scorer reports nothing for it.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.verifier import common
from core.verifier.import_map import (
    DIST_NAME_NOT_IMPORTABLE,
    IMPORT_TO_DIST,
    OFFLINE_KNOWN_PYPI,
    REMOVED_STDLIB,
    normalize_dist,
)
from core.verifier.local_modules import is_local_module

# ── Default TTL for in-memory cache entries (seconds) ──────────────
_DEFAULT_TTL: int = common.TTL_FOUND

ENV_IGNORE_INSTALLED = "HALLUGUARD_IGNORE_INSTALLED"


@dataclass
class _CacheEntry:
    """Single cache record for a PyPI lookup."""
    exists: bool
    latest_version: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def is_expired(self, ttl: int = _DEFAULT_TTL) -> bool:
        return (time.time() - self.timestamp) > ttl


# ── Module-level caches ────────────────────────────────────────────
_cache: dict[str, _CacheEntry] = {}
_disk_cache = common.DiskCache("pypi")


def clear_cache() -> None:
    """Forget every cached answer (memory and in-process disk view)."""
    _cache.clear()
    _disk_cache.reset()


# ── Standard library detection ─────────────────────────────────────
_STDLIB: frozenset[str] = (
    frozenset(sys.stdlib_module_names)
    | frozenset(sys.builtin_module_names)
    | REMOVED_STDLIB
)


def is_standard_library(package_name: str) -> bool:
    """Return ``True`` if *package_name* is a Python standard library module."""
    return package_name in _STDLIB


def _is_installed(name: str) -> bool:
    if os.environ.get(ENV_IGNORE_INSTALLED):
        return False
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


# ── PyPI metadata ──────────────────────────────────────────────────
def _extract_meta(data: dict[str, Any]) -> dict[str, Any]:
    """Pull the maturity signals out of a PyPI JSON document."""
    info = data.get("info", {}) or {}
    releases = data.get("releases", {}) or {}
    upload_times: list[float] = []
    release_count = 0
    for files in releases.values():
        if not files:
            continue
        release_count += 1
        for f in files:
            stamp = f.get("upload_time_iso_8601") or f.get("upload_time")
            if not stamp:
                continue
            try:
                dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                upload_times.append(dt.timestamp())
            except ValueError:
                continue
    summary = str(info.get("summary") or "").lower()
    classifiers = info.get("classifiers") or []
    deprecated = (
        "deprecated" in summary
        or "dummy package" in summary
        or any("Inactive" in c for c in classifiers)
    )
    return {
        "release_count": release_count,
        "first_release_ts": min(upload_times) if upload_times else None,
        "deprecated": deprecated,
    }


def _public_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Convert stored meta into the fields exposed in the result dict."""
    out: dict[str, Any] = {}
    if "release_count" in meta:
        out["release_count"] = meta["release_count"]
    ts = meta.get("first_release_ts")
    if ts:
        out["first_release_days"] = int((time.time() - float(ts)) // 86_400)
    if meta.get("deprecated"):
        out["deprecated"] = True
    return out


# ── Single-package lookup ──────────────────────────────────────────
def check_package(
    package_name: str,
    *,
    offline: bool | None = None,
    local_roots: list[Path] | None = None,
) -> dict[str, Any]:
    """
    Verify whether the module *package_name* is real.

    Args:
        package_name: Top-level module name as written in the ``import``.
        offline: Never use the network (default: ``HALLUGUARD_OFFLINE``).
        local_roots: Directories searched for project-local modules.

    Returns:
        A dict with ``package``, ``exists`` (``True`` / ``False`` / ``None``),
        ``type`` and optional ``latest_version``, ``distribution``, ``hint``,
        ``error``, ``release_count``, ``first_release_days``, ``deprecated``.
    """
    result: dict[str, Any] = {"package": package_name, "exists": False}

    # 1. Standard library — always valid
    if is_standard_library(package_name):
        result.update(exists=True, type="stdlib")
        return result

    # 2. Project-local module
    if is_local_module(package_name, local_roots or []):
        result.update(exists=True, type="local")
        return result

    # 3. A distribution name used as an import name (``import pillow``)
    key = package_name.lower().replace("-", "_")
    if key in DIST_NAME_NOT_IMPORTABLE and not _is_installed(package_name):
        real = DIST_NAME_NOT_IMPORTABLE[key]
        result.update(exists=False, type="wrong_import_name", hint=real)
        return result

    # 4. Installed in the running environment
    if _is_installed(package_name):
        result.update(exists=True, type="installed")
        return result

    # 5. Curated import -> distribution mapping
    dist = IMPORT_TO_DIST.get(package_name)
    if dist is not None:
        result.update(exists=True, type="known_mapping", distribution=dist)
        return result
    dist = package_name

    # 6. Offline: only positive evidence from the curated list
    if common.is_offline(offline):
        if normalize_dist(dist) in OFFLINE_KNOWN_PYPI:
            result.update(exists=True, type="known_offline")
        else:
            result.update(exists=None, type="unverified", error="offline mode")
        return result

    norm = normalize_dist(dist)

    # 7a. In-memory TTL cache
    cached = _cache.get(norm)
    if cached is not None and not cached.is_expired():
        result.update(
            exists=cached.exists,
            type="pypi_cached",
            latest_version=cached.latest_version,
            **_public_meta(cached.meta),
        )
        return result

    # 7b. Disk cache
    disk = _disk_cache.get(norm)
    if disk is not None:
        entry = _CacheEntry(
            exists=bool(disk["exists"]),
            latest_version=disk.get("latest_version"),
            meta=disk.get("meta", {}),
        )
        _cache[norm] = entry
        result.update(
            exists=entry.exists,
            type="pypi_cached",
            latest_version=entry.latest_version,
            **_public_meta(entry.meta),
        )
        return result

    # 7c. Live PyPI API call
    lookup = common.http_get_json(f"https://pypi.org/pypi/{norm}/json")
    if lookup.state == "error":
        result.update(exists=None, type="unverified", error=lookup.error)
        return result

    exists = lookup.state == "found"
    latest_version: str | None = None
    meta: dict[str, Any] = {}
    if exists and lookup.data is not None:
        latest_version = (lookup.data.get("info") or {}).get("version")
        meta = _extract_meta(lookup.data)
    _cache[norm] = _CacheEntry(exists=exists, latest_version=latest_version, meta=meta)
    _disk_cache.put(
        norm, {"exists": exists, "latest_version": latest_version, "meta": meta}
    )
    result.update(
        exists=exists,
        type="pypi_api",
        latest_version=latest_version,
        **_public_meta(meta),
    )
    return result


# ── Batch check (called by the pipeline) ───────────────────────────
def check(
    tokens: dict[str, Any],
    *,
    offline: bool | None = None,
    local_roots: list[Path] | None = None,
) -> dict[str, Any]:
    """
    Verify all imports found in *tokens* (lookups run in parallel).

    Args:
        tokens: Output of ``python_parser.extract()``.
        offline: Never use the network.
        local_roots: Directories searched for project-local modules.

    Returns:
        ``{"verified_imports": {name: check_result, ...}}``
    """
    names = list(dict.fromkeys(tokens.get("imports", [])))
    results = common.parallel_map(
        lambda n: check_package(n, offline=offline, local_roots=local_roots), names
    )
    _disk_cache.flush()
    return {"verified_imports": dict(zip(names, results, strict=True))}
