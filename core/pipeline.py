"""
HalluGuard AI — End-to-End Analysis Pipeline.

This is the single entry point for the entire core engine.
It orchestrates:

1. AST parsing  (Python or JS/TS)
2. Knowledge verification  (PyPI or npm; tri-state, parallel, cached)
3. API attribute verification  (Python: ``requests.fetch_json`` ...)
4. RWKV scoring  (local model, log-probability signal; optional)
5. Hallucination scoring  (weighted blend)
6. Correction suggestions

Usage::

    from core.pipeline import analyze
    report = analyze(code, language="python")
    print(report.to_dict())
"""
from __future__ import annotations

from typing import Any

from core.corrector import suggestion_engine
from core.parser import js_parser, python_parser
from core.rwkv_engine import router as rwkv_router
from core.scorer.hallucination_scorer import HallucinationReport, compute
from core.verifier import api_checker, common, local_modules, npm_verifier, pypi_verifier

# ── Supported languages ───────────────────────────────────────────
_PYTHON_ALIASES = frozenset({"python", "py"})
_JS_ALIASES = frozenset({"javascript", "js"})
_TS_ALIASES = frozenset({"typescript", "ts"})

SUPPORTED_LANGUAGES = _PYTHON_ALIASES | _JS_ALIASES | _TS_ALIASES

_EXT = {"python": "py", "javascript": "js", "typescript": "ts"}


def canonical_language(language: str) -> str:
    """Normalise a language alias (``py``, ``JS``...) or raise ``ValueError``."""
    lang = language.lower()
    if lang in _PYTHON_ALIASES:
        return "python"
    if lang in _JS_ALIASES:
        return "javascript"
    if lang in _TS_ALIASES:
        return "typescript"
    raise ValueError(
        f"Unsupported language '{language}'. "
        "Choose from: python, javascript, typescript."
    )


def _attribute_findings(
    tokens: dict[str, Any], local_roots: list[Any]
) -> list[dict[str, Any]]:
    """Verify module attributes against the installed packages (Python)."""
    queries = api_checker.build_queries(tokens, local_roots)
    if not queries:
        return []
    results = api_checker.check_queries(list(queries))
    findings: list[dict[str, Any]] = []
    for query, locations in queries.items():
        res = results[query]
        if res.status == "skip":
            continue
        status = "unverified" if res.status == "unknown" else res.status
        for loc in locations:
            if status == "dynamic_missing":
                # Only direct calls on a known "columns-style" class are
                # errors; other dynamic receivers accept any name.
                flaggable = (
                    query.instance
                    and query.target in api_checker.FLAGGABLE_DYNAMIC_CLASSES
                ) or (not query.instance)
                if not flaggable or "." in query.path:
                    continue
            findings.append({
                "name": loc["name"], "line": loc["line"], "col": loc["col"],
                "status": status, "suggestions": res.suggestions,
            })
    return findings


def analyze(
    code: str,
    language: str = "python",
    file_name: str | None = None,
    weights: dict[str, float] | None = None,
    *,
    project_root: str | None = None,
    offline: bool | None = None,
    check_attributes: bool | None = None,
) -> HallucinationReport:
    """
    Run the full hallucination detection pipeline on *code*.

    Args:
        code:      Source code string to analyse.
        language:  ``"python"``, ``"javascript"`` or ``"typescript"``
                   (aliases ``py``, ``js``, ``ts`` accepted).
        file_name: Optional file name attached to the report; when it is an
                   existing file it also locates project-local modules.
        weights:   Optional weight overrides for the scorer
                   (keys: ``knowledge``, ``ast``, ``rwkv``).
        project_root: Directory used to resolve project-local Python modules
                   (overrides the location derived from *file_name*).
        offline:   Never use the network (default: ``HALLUGUARD_OFFLINE``).
        check_attributes: Verify ``module.attr`` calls against the installed
                   packages (default: on, ``HALLUGUARD_ATTR_CHECK=0`` disables).

    Returns:
        A fully populated ``HallucinationReport``.
    """
    lang = canonical_language(language)
    is_offline = common.is_offline(offline)

    # ── 1. Parse ───────────────────────────────────────────────
    local_roots: list[Any] = []
    if lang == "python":
        tokens = python_parser.extract(code, "python")
        local_roots = local_modules.candidate_roots(project_root, file_name)
    else:
        tokens = js_parser.extract(code, lang)

    # ── 2. Verify knowledge ────────────────────────────────────
    if lang == "python":
        knowledge = pypi_verifier.check(
            tokens, offline=is_offline, local_roots=local_roots
        )
    else:
        knowledge = npm_verifier.check(tokens, offline=is_offline)

    # ── 3. Verify module attributes (installed packages only) ──
    attributes: list[dict[str, Any]] = []
    if lang == "python" and api_checker.enabled(check_attributes):
        attributes = _attribute_findings(tokens, local_roots)

    # ── 4. RWKV scoring (None when unavailable / withheld) ─────
    routing = rwkv_router.score(code)
    rwkv_score = routing.final_score

    # ── 5. Compute risk score ──────────────────────────────────
    report = compute(
        tokens, knowledge, rwkv_score=rwkv_score, weights=weights,
        language=lang, attributes=attributes,
    )
    if is_offline:
        report.notes.append(
            "offline mode: imports not in the curated list were not verified"
        )
    if report.unverified:
        report.notes.append(
            "could not be verified (network error or offline): "
            + ", ".join(report.unverified)
        )

    # ── 6. Generate corrections ────────────────────────────────
    report.suggestions = suggestion_engine.suggest(report, language=lang)

    # ── 7. Attach file metadata ────────────────────────────────
    report.file = file_name if file_name else f"snippet.{_EXT[lang]}"
    return report
