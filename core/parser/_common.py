"""
Shared helpers for the tree-sitter based parsers.

tree-sitter reports **byte** offsets into the UTF-8 encoded source, so any
slicing must be done on ``bytes`` and decoded afterwards (slicing the ``str``
directly shifts every token after the first non-ASCII character).
"""
from __future__ import annotations

from typing import Any

from tree_sitter import Node


class Source:
    """UTF-8 view of a source string with byte-correct node helpers."""

    def __init__(self, code: str) -> None:
        self.raw: bytes = code.encode("utf-8")

    def text(self, node: Node) -> str:
        """Return the exact source text of *node*."""
        return self.raw[node.start_byte : node.end_byte].decode("utf-8", "replace")

    def location(self, node: Node) -> tuple[int, int]:
        """Return ``(line, col)``: 1-based line, 0-based **character** column."""
        line_start = self.raw.rfind(b"\n", 0, node.start_byte) + 1
        col = len(self.raw[line_start : node.start_byte].decode("utf-8", "replace"))
        return node.start_point[0] + 1, col


def make_location(name: str, line: int, col: int) -> dict[str, Any]:
    """Build the ``{name, line, col}`` record exposed by the parsers."""
    return {"name": name, "line": line, "col": col}


def first_lines(locations: list[dict[str, Any]]) -> dict[str, int]:
    """Map each name to the line of its first occurrence."""
    first: dict[str, int] = {}
    for loc in locations:
        first.setdefault(loc["name"], loc["line"])
    return first
