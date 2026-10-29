"""
Resolution of project-local Python modules.

An ``import utils`` that refers to ``<project>/utils.py`` or
``<project>/utils/`` is not a registry package and must never be looked up
on PyPI (nor reported as a hallucination).
"""
from __future__ import annotations

import os
from pathlib import Path

_PROJECT_MARKERS = ("pyproject.toml", "setup.py", "setup.cfg", ".git")
_MAX_PARENTS = 6


def candidate_roots(
    project_root: str | os.PathLike[str] | None = None,
    file_name: str | None = None,
) -> list[Path]:
    """
    Directories in which a local module may live.

    * explicit *project_root* (plus its ``src/`` sub-directory);
    * otherwise, when *file_name* is an existing file, its directory and its
      ancestors up to the project root (first directory holding a project
      marker), plus their ``src/`` sub-directories.

    Returns an empty list when nothing can be resolved (snippets analysed
    without a file on disk): no module is then considered local.
    """
    roots: list[Path] = []

    def _add(path: Path) -> None:
        for p in (path, path / "src"):
            if p.is_dir() and p not in roots:
                roots.append(p)

    if project_root:
        _add(Path(project_root).resolve())
    elif file_name and os.path.isfile(file_name):
        current = Path(file_name).resolve().parent
        for _ in range(_MAX_PARENTS):
            _add(current)
            if any((current / m).exists() for m in _PROJECT_MARKERS):
                break
            if current.parent == current:
                break
            current = current.parent
    return roots


def is_local_module(name: str, roots: list[Path]) -> bool:
    """Return ``True`` if *name* is a module or package under one of *roots*."""
    if not name or not roots:
        return False
    for root in roots:
        if (root / f"{name}.py").is_file() or (root / f"{name}.pyi").is_file():
            return True
        if (root / name).is_dir():
            return True
    return False
