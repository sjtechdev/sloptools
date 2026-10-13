"""Which .py files make up a codebase."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePosixPath

TEST_EXCLUDES = ("test", "tests", "testing", "conftest.py")
DEFAULT_EXCLUDES = TEST_EXCLUDES + (
    "migrations", "vendor", "vendored", "third_party", "_vendor", "node_modules",
    "build", "dist", ".venv", "venv", "site-packages", "docs", "examples", "setup.py",
)


def is_excluded(rel: PurePosixPath, excludes: tuple[str, ...], include_tests: bool = False) -> bool:
    """Excluded if any path segment (or the filename) is in `excludes`, if
    any directory is hidden (.tox, .mypy_cache, ...), or, unless
    `include_tests`, if the filename looks like a test module."""
    parts = [s.lower() for s in rel.parts]
    name = parts[-1]
    if set(parts) & set(excludes):
        return True
    if any(p.startswith(".") for p in parts[:-1]):
        return True
    return not include_tests and (name.startswith("test_") or name.endswith("_test.py"))


def _git_ls_files(root: Path) -> list[str] | None:
    """Tracked plus untracked-but-not-ignored .py files, or None if `root`
    isn't inside a git work tree (or git isn't installed). Using git means
    .gitignore is respected for free."""
    try:
        p = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
             "--exclude-standard", "--", "*.py"],
            capture_output=True, check=False,
        )
    except OSError:
        return None
    if p.returncode != 0:
        return None
    rels = {r for r in p.stdout.decode("utf-8", "surrogateescape").split("\0") if r}
    # --cached also lists tracked files deleted from the work tree
    return [r for r in rels if (root / r).is_file()]


def _walk_files(root: Path, excludes: tuple[str, ...]) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        # prune in place so we never descend into .venv, node_modules, ...
        dirnames[:] = [d for d in dirnames if d.lower() not in excludes and not d.startswith(".")]
        rel_dir = Path(dirpath).relative_to(root)
        out.extend((rel_dir / f).as_posix() for f in filenames if f.endswith(".py"))
    return out


def list_python_files(root: Path, excludes: tuple[str, ...], include_tests: bool = False) -> list[str]:
    """Sorted posix paths, relative to `root`. With `include_tests`, the
    test-file name check is skipped and TEST_EXCLUDES are dropped from
    `excludes`."""
    if include_tests:
        excludes = tuple(e for e in excludes if e not in TEST_EXCLUDES)
    rels = _git_ls_files(root)
    if rels is None:
        rels = _walk_files(root, excludes)
    return sorted(r for r in rels if not is_excluded(PurePosixPath(r), excludes, include_tests))
