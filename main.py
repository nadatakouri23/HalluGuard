"""
HalluGuard AI — Quick demo entry-point.

Run with:  python main.py
"""
import json

from core.pipeline import analyze

PYTHON_EXAMPLE = """\
import requests
import this_library_does_not_exist_at_all
import sys
from os.path import join

def main():
    print(sys.version)
    response = requests.get("https://api.github.com")
    data = this_library_does_not_exist_at_all.make_magic()
    fetchUserData("http://example.com")
"""

JS_EXAMPLE = """\
import express from 'express';
import { magicHelper } from 'nonexistent-lib-xyz';
const axios = require('axios');
const fake  = require('totally-fake-package-abc');

app.get('/', (req, res) => {
    const data = axios.get('/api');
    fetch('https://example.com/api');
});
"""


def _divider(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def main() -> None:
    # ── Python analysis ────────────────────────────────────────
    _divider("Python Analysis")
    print(PYTHON_EXAMPLE.strip())
    print()

    py_report = analyze(PYTHON_EXAMPLE, language="python")
    print(json.dumps(py_report.to_dict(), indent=2, ensure_ascii=False))

    # ── JavaScript analysis ────────────────────────────────────
    _divider("JavaScript Analysis")
    print(JS_EXAMPLE.strip())
    print()

    js_report = analyze(JS_EXAMPLE, language="javascript")
    print(json.dumps(js_report.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
