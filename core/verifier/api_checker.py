"""
API attribute verification (``requests.fetch_json`` and friends).

Checking that ``requests`` exists on PyPI says nothing about whether
``requests.fetch_json`` exists.  This module resolves every dotted call whose
root is a module alias (``import requests as r; r.get``) or an instance of a
class created in the file (``df = pd.DataFrame(); df.magic()``) against the
**real API of the package installed in the running environment**.

How: for each target module a short-lived ``python -I`` subprocess imports it
and walks the attribute chain with ``getattr``.  The subprocess protects the
analyser from import side effects (crash, ``sys.exit``, prints) and has a
timeout.  Results are tri-state-like statuses:

``ok`` | ``missing`` | ``missing_instance`` | ``dynamic_missing`` | ``skip`` | ``unknown``

``skip`` means the receiver's type cannot be inferred (nothing to check).
``unknown`` covers every case where the truth cannot be established (package
not installed, import error, timeout): nothing is reported for it.

Limits (by design): only modules importable in the current interpreter can be
checked; variable types are inferred only for ``var = Class(...)`` with a single
assignment; instances of classes defining ``__getattr__`` are only checked for
direct calls.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any

ENV_ATTR_CHECK = "HALLUGUARD_ATTR_CHECK"
_MARKER = "@@HALLUGUARD@@"
_TIMEOUT = 20.0
_MAX_TARGETS = 12

#: Classes whose instances resolve unknown attributes dynamically (DataFrame
#: columns) *but* where calling a missing name is still a genuine error.  Any
#: other dynamic class (``Mock``, RPC proxies...) legitimately accepts every
#: name, so a miss on it is never reported.
FLAGGABLE_DYNAMIC_CLASSES: frozenset[str] = frozenset({"pandas.DataFrame", "pandas.Series"})

#: Importing these has visible side effects (opens a browser, prints a poem).
_NEVER_IMPORT = frozenset({"antigravity", "this", "idlelib", "turtledemo"})

_CHILD_SCRIPT = r"""
import sys, json, inspect, importlib, difflib

req = json.loads(sys.stdin.read())
target, instance, paths = req["target"], req["instance"], req["paths"]
out = {}

def emit():
    sys.stdout.write("\n@@HALLUGUARD@@" + json.dumps(out) + "\n")
    sys.stdout.flush()

def resolve_base(name):
    try:
        return importlib.import_module(name)
    except Exception:
        pass
    if "." in name:
        parent, _, last = name.rpartition(".")
        try:
            return getattr(importlib.import_module(parent), last)
        except Exception:
            return None
    return None

def is_dynamic(obj):
    if inspect.ismodule(obj):
        return "__getattr__" in vars(obj)
    holder = obj if inspect.isclass(obj) else type(obj)
    return hasattr(holder, "__getattr__")

try:
    base = resolve_base(target)
except BaseException:
    base = None
if base is None or (instance and not inspect.isclass(base)):
    # "skip": the result of a plain function call has no inferable type.
    verdict = "unknown" if base is None else "skip"
    for p in paths:
        out[p] = [verdict, []]
    emit()
    sys.exit(0)

for path in paths:
    obj = base
    status, suggestions = "ok", []
    for seg in path.split("."):
        try:
            obj = getattr(obj, seg)
            continue
        except AttributeError:
            pass
        except BaseException:
            status = "unknown"
            break
        if inspect.ismodule(obj):
            try:
                obj = importlib.import_module(obj.__name__ + "." + seg)
                continue
            except BaseException:
                pass
        status = "dynamic_missing" if is_dynamic(obj) else "missing"
        if status == "missing" and instance and obj is base:
            status = "missing_instance"
        names = [n for n in dir(obj) if not n.startswith("_")]
        suggestions = difflib.get_close_matches(seg, names, n=3, cutoff=0.6)
        break
    out[path] = [status, suggestions]
emit()
"""


@dataclass(frozen=True)
class AttrQuery:
    """One attribute chain to verify."""
    target: str       # dotted module / object to start from (``numpy``, ``pandas.DataFrame``)
    path: str         # attribute chain below the target (``fetch_json``)
    instance: bool = False  # True: *target* is a class and the chain applies to an instance


@dataclass
class AttrResult:
    status: str
    suggestions: list[str] = field(default_factory=list)


_results: dict[AttrQuery, AttrResult] = {}


def enabled(flag: bool | None = None) -> bool:
    """Resolve the enable flag: explicit argument first, then environment."""
    if flag is not None:
        return flag
    return os.environ.get(ENV_ATTR_CHECK, "1").strip().lower() not in ("0", "false", "no")


def _importable(top_level: str, local_roots: list[Any]) -> bool:
    if top_level in _NEVER_IMPORT:
        return False
    from core.verifier.local_modules import is_local_module

    if is_local_module(top_level, local_roots):
        return False
    try:
        return importlib.util.find_spec(top_level) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def build_queries(
    tokens: dict[str, Any], local_roots: list[Any] | None = None
) -> dict[AttrQuery, list[dict[str, Any]]]:
    """
    Turn the parser's ``method_calls`` into attribute queries.

    Returns ``{query: [location, ...]}`` where each location is the
    ``{"name", "line", "col"}`` record of the original call.
    """
    aliases: dict[str, str] = tokens.get("aliases", {})
    assignments: dict[str, list[str]] = tokens.get("assignments", {})
    roots = local_roots or []
    queries: dict[AttrQuery, list[dict[str, Any]]] = {}

    for loc in tokens.get("method_call_locations", []):
        text: str = loc["name"]
        if "(" in text or "[" in text or " " in text:
            continue
        root, _, rest = text.partition(".")
        if not rest or root in ("self", "cls"):
            continue

        query: AttrQuery | None = None
        if root in aliases:
            target = aliases[root]
            if _importable(target.split(".")[0], roots):
                query = AttrQuery(target, rest)
        elif root in assignments and len(set(assignments[root])) == 1:
            callee = assignments[root][0]
            c_root, _, c_rest = callee.partition(".")
            if c_root in aliases:
                target = aliases[c_root] + (f".{c_rest}" if c_rest else "")
                if _importable(target.split(".")[0], roots):
                    query = AttrQuery(target, rest, instance=True)
        if query is not None:
            queries.setdefault(query, []).append(loc)
    return queries


def _run_child(target: str, instance: bool, paths: list[str]) -> dict[str, AttrResult]:
    payload = json.dumps({"target": target, "instance": instance, "paths": paths})
    unknown = {p: AttrResult("unknown") for p in paths}
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _CHILD_SCRIPT],
            input=payload,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            cwd=tempfile.gettempdir(),
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return unknown
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith(_MARKER):
            try:
                raw = json.loads(line[len(_MARKER):])
            except ValueError:
                return unknown
            return {p: AttrResult(*raw[p]) if p in raw else AttrResult("unknown")
                    for p in paths}
    return unknown


def check_queries(queries: list[AttrQuery]) -> dict[AttrQuery, AttrResult]:
    """Resolve *queries* (one subprocess per distinct target)."""
    pending: dict[tuple[str, bool], list[str]] = {}
    for q in queries:
        if q not in _results:
            pending.setdefault((q.target, q.instance), []).append(q.path)

    for count, ((target, instance), paths) in enumerate(pending.items()):
        if count >= _MAX_TARGETS:
            for p in paths:
                _results[AttrQuery(target, p, instance)] = AttrResult("unknown")
            continue
        for path, res in _run_child(target, instance, sorted(set(paths))).items():
            _results[AttrQuery(target, path, instance)] = res
    return {q: _results[q] for q in queries}


def clear_cache() -> None:
    """Forget cached results (used by tests)."""
    _results.clear()
