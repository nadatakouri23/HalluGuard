"""
npm Registry Knowledge Verifier.

For each JavaScript/TypeScript import, ``require()`` or dynamic ``import()``,
decides whether the package is real.  Resolution order:

1. local specifiers (``./x``, ``../x``, ``/x``, ``#subpath``);
2. Node.js built-ins (``fs``, ``node:path``, ``fs/promises``...);
3. offline: curated list of popular packages, otherwise *undetermined*;
4. cache (memory, then disk), then the live npm registry.

As for PyPI, ``exists`` is tri-state (``True`` / ``False`` / ``None``): a
network failure never turns into "the package does not exist".
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from core.verifier import common
from core.verifier.import_map import OFFLINE_KNOWN_NPM

# ── Default TTL for in-memory cache entries (seconds) ──────────────
_DEFAULT_TTL: int = common.TTL_FOUND

#: Abbreviated metadata: small payload even for packages with thousands of
#: versions (dist-tags + versions, no readme).
_NPM_HEADERS = {"Accept": "application/vnd.npm.install-v1+json"}


@dataclass
class _CacheEntry:
    """Single cache record for an npm lookup."""
    exists: bool
    latest_version: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def is_expired(self, ttl: int = _DEFAULT_TTL) -> bool:
        return (time.time() - self.timestamp) > ttl


# ── Module-level caches ────────────────────────────────────────────
_cache: dict[str, _CacheEntry] = {}
_disk_cache = common.DiskCache("npm")


def clear_cache() -> None:
    """Forget every cached answer."""
    _cache.clear()
    _disk_cache.reset()


# ── Node.js built-in modules ──────────────────────────────────────
_NODE_BUILTINS: frozenset[str] = frozenset({
    "assert", "async_hooks", "buffer", "child_process", "cluster", "console",
    "constants", "crypto", "dgram", "diagnostics_channel", "dns", "domain",
    "events", "fs", "http", "http2", "https", "inspector", "module", "net",
    "os", "path", "perf_hooks", "process", "punycode", "querystring",
    "readline", "repl", "stream", "string_decoder", "sys", "timers", "tls",
    "trace_events", "tty", "url", "util", "v8", "vm", "wasi",
    "worker_threads", "zlib",
})

#: Prefixes that mark a module as runtime-provided regardless of its name
#: (``node:test``, ``node:sqlite``, ``bun:sqlite``...).
_RUNTIME_PREFIXES = ("node:", "bun:", "deno:")


def is_node_builtin(module_name: str) -> bool:
    """Return ``True`` if *module_name* is a Node.js built-in module."""
    if module_name.startswith(_RUNTIME_PREFIXES):
        return True
    return module_name in _NODE_BUILTINS


def _extract_package_name(specifier: str) -> str:
    """
    Normalize an npm specifier to its top-level package name.

    - ``@scope/pkg/sub`` -> ``@scope/pkg``
    - ``lodash/fp`` -> ``lodash``
    - Relative paths (``./``, ``../``), absolute paths and ``#`` subpath
      imports are returned as-is (they are local).
    - ``node:fs/promises`` -> ``node:fs``
    """
    specifier = specifier.strip("'\"")
    if specifier.startswith((".", "/", "#")):
        return specifier  # local import, skip
    if specifier.startswith("@"):
        parts = specifier.split("/")
        return "/".join(parts[:2]) if len(parts) >= 2 else specifier
    return specifier.split("/")[0]


def _extract_meta(data: dict[str, Any]) -> dict[str, Any]:
    versions = data.get("versions") or {}
    latest = (data.get("dist-tags") or {}).get("latest")
    latest_doc = versions.get(latest) if latest else None
    meta: dict[str, Any] = {"version_count": len(versions)}
    if isinstance(latest_doc, dict) and latest_doc.get("deprecated"):
        meta["deprecated"] = True
    return meta


# ── Single-package lookup ──────────────────────────────────────────
def check_package(
    module_specifier: str, *, offline: bool | None = None
) -> dict[str, Any]:
    """
    Verify whether an npm package exists on the registry.

    Args:
        module_specifier: The raw import/require string.
        offline: Never use the network (default: ``HALLUGUARD_OFFLINE``).

    Returns:
        A dict with ``package``, ``exists`` (``True`` / ``False`` / ``None``),
        ``type`` and optional ``latest_version``, ``version_count``,
        ``deprecated`` or ``error``.
    """
    pkg = _extract_package_name(module_specifier)
    result: dict[str, Any] = {"package": pkg, "exists": False}

    # Local (relative / absolute / #subpath) imports
    if pkg.startswith((".", "/", "#")):
        result.update(exists=True, type="local")
        return result

    # Node built-in
    if is_node_builtin(pkg):
        result.update(exists=True, type="node_builtin")
        return result

    # Offline: only positive evidence from the curated list
    if common.is_offline(offline):
        if pkg in OFFLINE_KNOWN_NPM:
            result.update(exists=True, type="known_offline")
        else:
            result.update(exists=None, type="unverified", error="offline mode")
        return result

    # In-memory TTL cache
    cached = _cache.get(pkg)
    if cached is not None and not cached.is_expired():
        result.update(
            exists=cached.exists,
            type="npm_cached",
            latest_version=cached.latest_version,
            **cached.meta,
        )
        return result

    # Disk cache
    disk = _disk_cache.get(pkg)
    if disk is not None:
        entry = _CacheEntry(
            exists=bool(disk["exists"]),
            latest_version=disk.get("latest_version"),
            meta=disk.get("meta", {}),
        )
        _cache[pkg] = entry
        result.update(
            exists=entry.exists,
            type="npm_cached",
            latest_version=entry.latest_version,
            **entry.meta,
        )
        return result

    # Live npm registry call
    lookup = common.http_get_json(
        f"https://registry.npmjs.org/{quote(pkg, safe='@')}", headers=_NPM_HEADERS
    )
    if lookup.state == "error":
        result.update(exists=None, type="unverified", error=lookup.error)
        return result

    exists = lookup.state == "found"
    latest_version: str | None = None
    meta: dict[str, Any] = {}
    if exists and lookup.data is not None:
        latest_version = (lookup.data.get("dist-tags") or {}).get("latest")
        meta = _extract_meta(lookup.data)
    _cache[pkg] = _CacheEntry(exists=exists, latest_version=latest_version, meta=meta)
    _disk_cache.put(
        pkg, {"exists": exists, "latest_version": latest_version, "meta": meta}
    )
    result.update(exists=exists, type="npm_api", latest_version=latest_version, **meta)
    return result


# ── Batch check (called by the pipeline) ───────────────────────────
def check(tokens: dict[str, Any], *, offline: bool | None = None) -> dict[str, Any]:
    """
    Verify all imports / require() calls found in *tokens* (in parallel).

    Args:
        tokens: Output of ``js_parser.extract()``.
        offline: Never use the network.

    Returns:
        ``{"verified_imports": {name: check_result, ...}}``
    """
    modules: list[str] = []
    modules.extend(tokens.get("imports", []))
    modules.extend(tokens.get("require_calls", []))

    by_pkg: dict[str, str] = {}
    for mod in modules:
        by_pkg.setdefault(_extract_package_name(mod), mod)

    names = list(by_pkg)
    results = common.parallel_map(
        lambda p: check_package(by_pkg[p], offline=offline), names
    )
    _disk_cache.flush()
    return {"verified_imports": dict(zip(names, results, strict=True))}
