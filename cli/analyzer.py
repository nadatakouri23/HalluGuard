"""
HalluGuard AI — CLI Analyzer.

Designed for headless operation and CI/CD pipelines.  Takes a list of files,
runs the analysis and prints the JSON array of reports to stdout (logs go to
stderr, so stdout stays machine-readable).

Examples::

    halluguard src/app.py web/index.ts
    halluguard --offline --fail-on HIGH $(git diff --name-only)
    python -m cli.analyzer --project-root . file.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from core.pipeline import analyze
from core.scorer.hallucination_scorer import SEVERITY_ORDER

_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript",
    ".cts": "typescript",
}


def ext_to_lang(ext: str) -> str | None:
    """Map a file extension to an analysis language (``None`` if unsupported)."""
    return _EXTENSIONS.get(ext.lower())


def format_text(reports: list[dict[str, Any]]) -> str:
    """Human-readable rendering: ``file:line:col: SEVERITY type token - why``."""
    lines: list[str] = []
    for rep in reports:
        if rep.get("error"):
            lines.append(f"{rep['file']}: ERROR {rep['error']}")
            continue
        for h in rep["hallucinations"]:
            lines.append(
                f"{rep['file']}:{h['line']}:{h['column']}: {h['severity']} "
                f"{h['type']} {h['token']} - {h['explanation']}"
            )
        summary = (
            f"{rep['file']}: severity={rep['severity']} risk={rep['risk_score']} "
            f"confidence={rep['confidence']}"
        )
        if rep.get("unverified"):
            summary += f" unverified={','.join(rep['unverified'])}"
        lines.append(summary)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="halluguard", description="HalluGuard AI analysis CLI"
    )
    parser.add_argument("files", nargs="+", help="Files to analyze")
    parser.add_argument(
        "--offline", action="store_true",
        help="Never query PyPI/npm (only curated knowledge is used).",
    )
    parser.add_argument(
        "--project-root", default=None,
        help="Directory used to resolve project-local Python modules.",
    )
    parser.add_argument(
        "--no-attr-check", action="store_true",
        help="Do not verify module attributes against installed packages.",
    )
    parser.add_argument(
        "--format", choices=["json", "text"], default="json",
        help="json (default, one array on stdout) or text (one line per finding).",
    )
    parser.add_argument(
        "--fail-on", choices=[s for s in SEVERITY_ORDER if s != "NONE"], default=None,
        help="Exit with status 1 if an issue of this severity or higher is found.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    reports: list[dict[str, Any]] = []

    for file_path in args.files:
        if not os.path.isfile(file_path):
            print(f"halluguard: skipping '{file_path}' (not a file)", file=sys.stderr)
            continue

        lang = ext_to_lang(os.path.splitext(file_path)[1])
        if not lang:
            continue

        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                code = f.read()
            report = analyze(
                code,
                language=lang,
                file_name=file_path,
                project_root=args.project_root,
                offline=True if args.offline else None,
                check_attributes=False if args.no_attr_check else None,
            )
            reports.append(report.to_dict())
        except Exception as e:  # noqa: BLE001 - one bad file must not stop the run
            # Inject the error directly into the report format for debugging
            reports.append({
                "file": file_path,
                "risk_score": 0,
                "risk_level": "NONE",
                "severity": "NONE",
                "confidence": "LOW",
                "hallucinations": [],
                "suggestions": [],
                "unverified": [],
                "notes": [],
                "error": str(e),
            })

    if args.format == "text":
        print(format_text(reports))
    else:
        # Output strictly the JSON array so the GitHub Action can parse it
        print(json.dumps(reports, ensure_ascii=False))

    if args.fail_on:
        threshold = SEVERITY_ORDER[args.fail_on]
        for rep in reports:
            if any(SEVERITY_ORDER.get(h["severity"], 0) >= threshold
                   for h in rep["hallucinations"]):
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
