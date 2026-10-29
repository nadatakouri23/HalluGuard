"""
Shared plumbing for the registry verifiers (PyPI / npm).

* **Tri-state lookups** – a registry answer is ``found``, ``missing`` or
  ``error``.  A network failure is *never* reported as "missing": the caller
  gets ``exists=None`` (undetermined) and must not flag anything.
* **Retry with backoff** on timeouts, connection errors, HTTP 429 and 5xx.
* **Disk cache** (JSON, TTL) shared across processes, so the CLI and the
  GitHub Action do not re-query the registry on every run.
* **Offline mode** (``HALLUGUARD_OFFLINE=1`` or ``offline=True``): no network
  call is ever made.
* **Parallel lookups** with a small thread pool.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import requests

ENV_OFFLINE = "HALLUGUARD_OFFLINE"
ENV_CACHE_DIR = "HALLUGUARD_CACHE_DIR"
ENV_NO_DISK_CACHE = "HALLUGUARD_NO_DISK_CACHE"

DEFAULT_TIMEOUT = 5.0
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF = 0.5
MAX_WORKERS = 8

#: Time-to-live of a definitive "exists" answer (seconds).
TTL_FOUND = 86_400
#: Time-to-live of a definitive "does not exist" answer (a package can be
#: published at any time, so keep this one short).
TTL_MISSING = 3_600

_T = TypeVar("_T")
_R = TypeVar("_R")


@dataclass
class Lookup:
    """Outcome of one registry request."""
    state: str  # "found" | "missing" | "error"
    data: dict[str, Any] | None = None
    error: str | None = None


def is_offline(offline: bool | None = None) -> bool:
    """Resolve the offline flag: explicit argument first, then environment."""
    if offline is not None:
        return offline
    return os.environ.get(ENV_OFFLINE, "").strip().lower() in ("1", "true", "yes")


def http_get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF,
) -> Lookup:
    """GET *url* and classify the answer as found / missing / error."""
    last_error = "unknown error"
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if resp.status_code == 200:
                try:
                    return Lookup("found", data=resp.json())
                except ValueError as exc:
                    return Lookup("error", error=f"invalid JSON: {exc}")
            if resp.status_code in (404, 410):
                return Lookup("missing")
            last_error = f"HTTP {resp.status_code}"
            if resp.status_code not in (429, 500, 502, 503, 504):
                break  # 403, 401, ... : retrying will not help
        if attempt < retries:
            time.sleep(backoff * (2 ** attempt))
    return Lookup("error", error=last_error)


# ── Disk cache ─────────────────────────────────────────────────────
def cache_dir() -> Path:
    """Directory holding the registry caches."""
    configured = os.environ.get(ENV_CACHE_DIR)
    return Path(configured) if configured else Path.home() / ".cache" / "halluguard"


class DiskCache:
    """Tiny JSON-file cache: ``{key: {"exists": bool, "ts": float, ...}}``."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, Any]] | None = None
        self._dirty = False

    @property
    def enabled(self) -> bool:
        return os.environ.get(ENV_NO_DISK_CACHE, "").strip().lower() not in (
            "1", "true", "yes",
        )

    def _path(self) -> Path:
        return cache_dir() / f"{self._name}.json"

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._entries is None:
            try:
                raw = json.loads(self._path().read_text(encoding="utf-8"))
                self._entries = raw if isinstance(raw, dict) else {}
            except (OSError, ValueError):
                self._entries = {}
        return self._entries

    def get(self, key: str) -> dict[str, Any] | None:
        """Return a non-expired entry, or ``None``."""
        if not self.enabled:
            return None
        with self._lock:
            entry = self._load().get(key)
        if entry is None:
            return None
        ttl = TTL_FOUND if entry.get("exists") else TTL_MISSING
        if time.time() - float(entry.get("ts", 0)) > ttl:
            return None
        return entry

    def put(self, key: str, entry: dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._load()[key] = {**entry, "ts": time.time()}
            self._dirty = True

    def flush(self) -> None:
        """Persist pending entries (best effort, atomic replace)."""
        if not self.enabled:
            return
        with self._lock:
            if not self._dirty or self._entries is None:
                return
            path = self._path()
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(f".{os.getpid()}.tmp")
                tmp.write_text(json.dumps(self._entries), encoding="utf-8")
                os.replace(tmp, path)
                self._dirty = False
            except OSError:
                pass  # a read-only cache directory must never break analysis

    def reset(self) -> None:
        """Forget the in-memory view (used by tests)."""
        with self._lock:
            self._entries = None
            self._dirty = False


def parallel_map(
    fn: Callable[[_T], _R], items: Iterable[_T], max_workers: int = MAX_WORKERS
) -> list[_R]:
    """Apply *fn* to *items* with a thread pool, preserving order."""
    seq = list(items)
    if len(seq) <= 1:
        return [fn(item) for item in seq]
    with ThreadPoolExecutor(max_workers=min(max_workers, len(seq))) as pool:
        return list(pool.map(fn, seq))
