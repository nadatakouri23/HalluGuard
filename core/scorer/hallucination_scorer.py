"""
Hallucination Scorer — combined scoring algorithm.

Blends three signal sources with configurable weights:

- **Knowledge score** : imports and API attributes that do not exist.
- **AST score**       : calls to names that are neither builtins, defined in
  the file, imported, nor aliased.
- **RWKV score**      : local model signal (when available and calibrated).

Scoring model
-------------
Each issue is worth a number of *points*; a source score is a concave
saturating function of its points, ``100 * (1 - exp(-points / scale))``.
Unlike a per-import ``100 / N`` split or a hard cap, one fabricated import is
never diluted by the valid ones, and many small issues approach but never hit
100 abruptly.

Two different summaries are exposed on the report:

- ``risk_score`` (0-100) – the blended aggregate, meant for ranking/trends;
- ``severity`` – the severity of the *worst issue* (``NONE`` when clean),
  which is what gating (CI, PR checks) should use.

``confidence`` states how much of the file could actually be verified (it is
lowered by unverifiable imports, e.g. when offline), not how risky it is.
"""
from __future__ import annotations

import builtins
import math
from dataclasses import dataclass, field
from typing import Any

# ── Risk-level thresholds (aggregate score -> label) ───────────────
_THRESHOLDS: dict[str, tuple[int, int]] = {
    "LOW":      (1, 25),
    "MEDIUM":   (26, 50),
    "HIGH":     (51, 75),
    "CRITICAL": (76, 100),
}

SEVERITY_ORDER: dict[str, int] = {
    "NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4,
}

# ── Configurable weight defaults ────────────────────────────────
DEFAULT_WEIGHTS: dict[str, float] = {
    "knowledge": 0.50,
    "ast":       0.30,
    "rwkv":      0.20,
}

# ── Issue points and saturation scales ──────────────────────────
POINTS: dict[str, float] = {
    "unknown_import": 50.0,
    "unknown_attribute": 40.0,        # HIGH (module attribute is certainly absent)
    "unknown_attribute_soft": 20.0,   # MEDIUM (instance / dynamic class)
    "suspicious_package": 8.0,
    "deprecated_package": 8.0,
    "unknown_function": 12.0,
}
KNOWLEDGE_SCALE = 30.0
AST_SCALE = 60.0

#: A package published a few weeks ago with a single release is a typical
#: slopsquatting profile; it is only worth a LOW note.
_YOUNG_PACKAGE_DAYS = 90

_PY_BUILTINS: frozenset[str] = frozenset(dir(builtins))

_JS_GLOBALS: frozenset[str] = frozenset({
    "require", "fetch", "setTimeout", "clearTimeout", "setInterval",
    "clearInterval", "setImmediate", "clearImmediate", "queueMicrotask",
    "structuredClone", "requestAnimationFrame", "cancelAnimationFrame",
    "parseInt", "parseFloat", "isNaN", "isFinite", "eval", "encodeURI",
    "encodeURIComponent", "decodeURI", "decodeURIComponent", "escape",
    "unescape", "atob", "btoa", "alert", "confirm", "prompt", "import",
    "super", "Object", "Function", "Array", "String", "Number", "Boolean",
    "Symbol", "BigInt", "Date", "RegExp", "Error", "TypeError", "RangeError",
    "SyntaxError", "ReferenceError", "EvalError", "URIError", "AggregateError",
    "Promise", "Map", "Set", "WeakMap", "WeakSet", "WeakRef", "Proxy",
    "Reflect", "Intl", "ArrayBuffer", "SharedArrayBuffer", "DataView",
    "Int8Array", "Uint8Array", "Uint8ClampedArray", "Int16Array", "Uint16Array",
    "Int32Array", "Uint32Array", "Float32Array", "Float64Array",
    "BigInt64Array", "BigUint64Array", "URL", "URLSearchParams",
    "AbortController", "AbortSignal", "Headers", "Request", "Response",
    "FormData", "Blob", "File", "TextEncoder", "TextDecoder", "Event",
    "EventTarget", "CustomEvent", "Buffer", "Worker", "WebSocket",
    "XMLHttpRequest", "IntersectionObserver", "MutationObserver",
    "ResizeObserver", "PerformanceObserver", "BroadcastChannel",
    "MessageChannel", "Notification", "Image", "Audio",
})


@dataclass
class HallucinationIssue:
    """A single detected hallucination."""
    line: int
    issue_type: str
    token: str
    explanation: str
    suggestion: str
    severity: str
    column: int = 0


@dataclass
class HallucinationReport:
    """Full analysis report returned by the scorer."""
    file: str = ""
    risk_score: int = 0
    confidence: str = "HIGH"
    hallucinations: list[HallucinationIssue] = field(default_factory=list)
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    severity: str = "NONE"
    risk_level: str = "NONE"
    unverified: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # Internal scores kept for debugging / benchmarks
    _knowledge_raw: float = 0.0
    _ast_raw: float = 0.0
    _rwkv_raw: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the universal JSON format."""
        return {
            "file": self.file,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "severity": self.severity,
            "confidence": self.confidence,
            "hallucinations": [
                {
                    "line": h.line,
                    "column": h.column,
                    "type": h.issue_type,
                    "token": h.token,
                    "explanation": h.explanation,
                    "suggestion": h.suggestion,
                    "severity": h.severity,
                }
                for h in self.hallucinations
            ],
            "suggestions": self.suggestions,
            "unverified": self.unverified,
            "notes": self.notes,
        }


def _severity_label(score: int) -> str:
    """Map a 0-100 aggregate score to a risk level (``NONE`` for 0)."""
    if score <= 0:
        return "NONE"
    for label, (lo, hi) in _THRESHOLDS.items():
        if lo <= score <= hi:
            return label
    return "CRITICAL"


def _saturate(points: float, scale: float) -> float:
    return 100.0 * (1.0 - math.exp(-points / scale))


def _first_occurrences(
    locations: list[dict[str, Any]], names: list[str], key: Any = None
) -> dict[str, tuple[int, int]]:
    """Map each name to the (line, col) of its first occurrence."""
    first: dict[str, tuple[int, int]] = {}
    for loc in locations:
        name = key(loc["name"]) if key else loc["name"]
        first.setdefault(name, (loc["line"], loc["col"]))
    for name in names:
        first.setdefault(name, (0, 0))  # hand-built tokens: position unknown
    return first


def compute(
    tokens: dict[str, Any],
    knowledge: dict[str, Any],
    rwkv_score: float | None = None,
    weights: dict[str, float] | None = None,
    *,
    language: str = "python",
    attributes: list[dict[str, Any]] | None = None,
) -> HallucinationReport:
    """
    Compute a hallucination report by blending multiple signal sources.

    Args:
        tokens:     Output of the AST parser (``extract()``).
        knowledge:  Output of the knowledge verifier (``check()``).
        rwkv_score: RWKV risk (0-100), or ``None`` / negative when unavailable.
        weights:    Optional weight overrides (keys: knowledge, ast, rwkv).
        language:   ``"python"`` or ``"javascript"``/``"typescript"``.
        attributes: Attribute-check findings (see ``pipeline``); each item has
                    ``name``, ``line``, ``col``, ``status``, ``suggestions``.

    Returns:
        A fully populated ``HallucinationReport``.
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    is_python = language.lower() in ("python", "py")
    issues: list[HallucinationIssue] = []
    knowledge_points = 0.0
    ast_points = 0.0

    # ── Knowledge: imports ─────────────────────────────────────
    verified = knowledge.get("verified_imports", {})
    if is_python:
        import_pos = _first_occurrences(
            tokens.get("import_locations", []), list(tokens.get("imports", []))
        )
    else:
        from core.verifier.npm_verifier import _extract_package_name

        import_pos = _first_occurrences(
            tokens.get("import_locations", []),
            list(tokens.get("imports", [])) + list(tokens.get("require_calls", [])),
            key=_extract_package_name,
        )

    unverified: list[str] = []
    for pkg_name, info in verified.items():
        exists = info.get("exists", False)
        line, col = import_pos.get(pkg_name, (0, 0))
        if exists is None:
            unverified.append(pkg_name)
            continue
        if not exists:
            knowledge_points += POINTS["unknown_import"]
            if info.get("type") == "wrong_import_name":
                hint = info.get("hint", "")
                explanation = (
                    f"'{pkg_name}' is a PyPI distribution name, not an importable "
                    f"module; the import name is '{hint}'."
                )
                suggestion = f"import {hint}"
            else:
                explanation = f"Package '{pkg_name}' was not found on the package registry."
                suggestion = "Verify package spelling or find a valid alternative."
            issues.append(HallucinationIssue(
                line=line, column=col, issue_type="unknown_import", token=pkg_name,
                explanation=explanation, suggestion=suggestion, severity="HIGH",
            ))
            continue
        if info.get("deprecated"):
            knowledge_points += POINTS["deprecated_package"]
            issues.append(HallucinationIssue(
                line=line, column=col, issue_type="deprecated_package", token=pkg_name,
                explanation=f"Package '{pkg_name}' is marked deprecated/inactive.",
                suggestion="Check for a maintained replacement.", severity="LOW",
            ))
        elif (
            info.get("release_count") == 1
            and info.get("first_release_days") is not None
            and info["first_release_days"] < _YOUNG_PACKAGE_DAYS
        ):
            knowledge_points += POINTS["suspicious_package"]
            issues.append(HallucinationIssue(
                line=line, column=col, issue_type="suspicious_package", token=pkg_name,
                explanation=(
                    f"Package '{pkg_name}' has a single release published "
                    f"{info['first_release_days']} days ago (possible name squatting)."
                ),
                suggestion="Verify the package is the one you intend to use.",
                severity="LOW",
            ))

    # ── Knowledge: attributes of real packages ─────────────────
    for item in attributes or []:
        status = item.get("status")
        if status not in ("missing", "missing_instance", "dynamic_missing"):
            if status == "unverified":
                unverified.append(item["name"])
            continue
        hard = status == "missing"
        suggestions = item.get("suggestions") or []
        prefix = item["name"].rpartition(".")[0]
        hint = (
            f"Did you mean '{prefix}.{suggestions[0]}'?" if suggestions
            else "Check the package documentation for the correct API."
        )
        knowledge_points += POINTS["unknown_attribute" if hard else "unknown_attribute_soft"]
        issues.append(HallucinationIssue(
            line=item.get("line", 0), column=item.get("col", 0),
            issue_type="unknown_attribute", token=item["name"],
            explanation=(
                f"'{item['name']}' does not exist in the installed package API."
                if hard else
                f"'{item['name']}' is not defined on the inferred class "
                "(instance or dynamic attribute: lower certainty)."
            ),
            suggestion=hint, severity="HIGH" if hard else "MEDIUM",
        ))

    # ── AST: unresolved bare calls ─────────────────────────────
    defined: set[str] = set(tokens.get("defined_names", []))
    for fi in tokens.get("from_imports", []):
        defined.update(fi.get("names", []))
    defined.update(tokens.get("aliases", {}).keys())
    defined.update(tokens.get("classes", []))
    known = defined | (_PY_BUILTINS if is_python else _JS_GLOBALS)

    if not tokens.get("star_imports"):
        call_pos = _first_occurrences(
            tokens.get("function_call_locations", []),
            list(tokens.get("function_calls", [])),
        )
        for fn in tokens.get("function_calls", []):
            if fn in known:
                continue
            line, col = call_pos.get(fn, (0, 0))
            ast_points += POINTS["unknown_function"]
            issues.append(HallucinationIssue(
                line=line, column=col, issue_type="unknown_function", token=fn,
                explanation=f"Function '{fn}()' is not a known builtin, definition or import.",
                suggestion=f"Check if '{fn}' should be imported or if it exists.",
                severity="MEDIUM",
            ))

    knowledge_score = _saturate(knowledge_points, KNOWLEDGE_SCALE)
    ast_score = _saturate(ast_points, AST_SCALE)

    # ── RWKV integration ──────────────────────────────────────
    rwkv_effective = 0.0
    rwkv_weight_active = w["rwkv"]
    if rwkv_score is not None and rwkv_score >= 0:
        rwkv_effective = rwkv_score
    else:
        # Redistribute RWKV weight equally among the other two sources
        rwkv_weight_active = 0.0
        remaining = w["rwkv"]
        w["knowledge"] += remaining / 2
        w["ast"] += remaining / 2

    # ── Weighted blend ────────────────────────────────────────
    raw = (
        knowledge_score * w["knowledge"]
        + ast_score * w["ast"]
        + rwkv_effective * rwkv_weight_active
    )
    risk_score = int(max(0, min(100, round(raw))))

    severity = max(
        (i.severity for i in issues), key=lambda s: SEVERITY_ORDER.get(s, 0),
        default="NONE",
    )

    # Confidence = share of verifiable items that could be decided.
    total_checks = len(verified) + len(attributes or [])
    pending = len(unverified)
    if total_checks == 0:
        confidence = "LOW"
    elif pending == 0:
        confidence = "HIGH"
    elif pending / total_checks <= 0.5:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return HallucinationReport(
        risk_score=risk_score,
        confidence=confidence,
        hallucinations=issues,
        severity=severity,
        risk_level=_severity_label(risk_score),
        unverified=unverified,
        _knowledge_raw=knowledge_score,
        _ast_raw=ast_score,
        _rwkv_raw=rwkv_effective,
    )
