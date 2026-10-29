"""
Correction / Suggestion Engine.

For each detected hallucination, generates actionable suggestions:

- Unknown import    -> exact known mistake, else fuzzy-match a real package
  (strict cutoff; no suggestion is better than a wrong one).
- Unknown function  -> exact match against a table of *commonly hallucinated
  names* only (no fuzzy matching: similar-looking names are unrelated).
- Unknown attribute -> the "did you mean" computed from the real package API.
"""
from __future__ import annotations

import difflib
from typing import Any

from core.verifier.import_map import (
    DIST_NAME_NOT_IMPORTABLE,
    IMPORT_TO_DIST,
    OFFLINE_KNOWN_NPM,
    OFFLINE_KNOWN_PYPI,
)

_PYTHON_ALIASES = frozenset({"python", "py"})

#: Cutoff for ``difflib`` fuzzy matching of package names.
FUZZY_CUTOFF = 0.8

# ── Commonly hallucinated names ───────────────────────────────────
# Only names that are *wrong*: valid-but-differently-named packages
# (cv2, yaml, PIL...) are handled by ``core.verifier.import_map``.
COMMON_PATTERNS: dict[str, dict[str, str]] = {
    # Fake import names -> real ones
    "requests2":     {"replacement": "requests",      "note": "No 'requests2' package; use 'requests'."},
    "beautifulsoup": {"replacement": "beautifulsoup4", "note": "Install 'beautifulsoup4' and import it as 'bs4'."},
    # Fake functions -> real equivalents (Python)
    "fetchUserData": {"replacement": "requests.get(url)", "note": "Common LLM hallucination; use requests.get().",
                      "replacement_js": "fetch(url)", "note_js": "Common LLM hallucination; use fetch()."},
    "getData":       {"replacement": "requests.get(url)", "note": "Generic hallucinated name; specify the real API call.",
                      "replacement_js": "fetch(url)", "note_js": "Generic hallucinated name; specify the real API call."},
    "sendRequest":   {"replacement": "requests.post(url, data=...)", "note": "Use requests.post() explicitly.",
                      "replacement_js": "fetch(url, { method: 'POST' })", "note_js": "Use fetch() explicitly."},
    "connectDB":     {"replacement": "sqlalchemy.create_engine(url)", "note": "Use SQLAlchemy or a real DB driver.",
                      "replacement_js": "new Pool(...)  // e.g. the 'pg' driver", "note_js": "Use a real DB driver."},
    "fetchFromAPI":  {"replacement": "requests.get(url)", "note": "Non-existent convenience function.",
                      "replacement_js": "fetch(url)", "note_js": "Non-existent convenience function."},
}


def _python_candidates() -> list[str]:
    """Real *import* names (not distribution names) used for fuzzy matching."""
    not_importable = set(DIST_NAME_NOT_IMPORTABLE)
    names = {
        n for n in OFFLINE_KNOWN_PYPI
        if n.replace("-", "_") not in not_importable
    }
    names.update(IMPORT_TO_DIST)
    return sorted(names)


_KNOWN_PYPI: list[str] = _python_candidates()
_KNOWN_NPM: list[str] = sorted(OFFLINE_KNOWN_NPM)


def _fuzzy_match(
    name: str, candidates: list[str], cutoff: float = FUZZY_CUTOFF
) -> str | None:
    """Return the closest match from *candidates*, or ``None``."""
    # A name can never be "the closest real package" to itself.
    pool = [c for c in candidates if c.lower() != name.lower()]
    matches = difflib.get_close_matches(name, pool, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def suggest(report: Any, language: str = "python") -> list[dict[str, Any]]:
    """
    Generate correction suggestions for each hallucination in *report*.

    Args:
        report: A ``HallucinationReport`` instance (from the scorer).
        language: ``"python"``/``"py"`` or ``"javascript"``/``"typescript"``
            (aliases are accepted).

    Returns:
        A list of suggestion dicts, each containing:
        ``token``, ``original_type``, ``suggestion``, ``explanation``,
        ``confidence``.
    """
    is_python = language.lower() in _PYTHON_ALIASES
    candidates = _KNOWN_PYPI if is_python else _KNOWN_NPM
    suggestions: list[dict[str, Any]] = []

    for issue in report.hallucinations:
        token = issue.token
        suggestion: dict[str, Any] = {
            "token": token,
            "original_type": issue.issue_type,
        }

        if issue.issue_type == "unknown_import":
            pattern = COMMON_PATTERNS.get(token)
            if pattern and "replacement_js" not in pattern:
                suggestion["suggestion"] = pattern["replacement"]
                suggestion["explanation"] = pattern["note"]
                suggestion["confidence"] = "HIGH"
            elif issue.suggestion.startswith("import "):
                # Distribution name used as import name: the scorer knows the fix.
                suggestion["suggestion"] = issue.suggestion.removeprefix("import ")
                suggestion["explanation"] = issue.explanation
                suggestion["confidence"] = "HIGH"
            else:
                match = _fuzzy_match(token, candidates)
                if match:
                    suggestion["suggestion"] = match
                    suggestion["explanation"] = (
                        f"Did you mean '{match}'? '{token}' was not found."
                    )
                    suggestion["confidence"] = "MEDIUM"
                else:
                    suggestion["suggestion"] = None
                    suggestion["explanation"] = (
                        f"No close match found for '{token}'. "
                        "Verify the package name manually."
                    )
                    suggestion["confidence"] = "LOW"

        elif issue.issue_type == "unknown_function":
            pattern = COMMON_PATTERNS.get(token)
            if pattern and "replacement_js" in pattern:
                key = "" if is_python else "_js"
                suggestion["suggestion"] = pattern[f"replacement{key}"]
                suggestion["explanation"] = pattern[f"note{key}"]
                suggestion["confidence"] = "HIGH"
            else:
                suggestion["suggestion"] = None
                suggestion["explanation"] = (
                    f"Function '{token}()' not recognized. "
                    "Ensure it is imported or defined."
                )
                suggestion["confidence"] = "LOW"

        elif issue.issue_type == "unknown_attribute":
            did_you_mean = issue.suggestion.startswith("Did you mean")
            suggestion["suggestion"] = (
                issue.suggestion.split("'")[1] if did_you_mean else None
            )
            suggestion["explanation"] = issue.explanation
            suggestion["confidence"] = "MEDIUM" if did_you_mean else "LOW"

        else:
            suggestion["suggestion"] = None
            suggestion["explanation"] = issue.explanation or "No automatic suggestion available."
            suggestion["confidence"] = "LOW"

        suggestions.append(suggestion)

    return suggestions
