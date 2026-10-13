"""Roots, and the units of code inside them that can be duplicated.

Milestone 1 handles functions and methods only.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from sloptools.common.discover import list_python_files
from sloptools.common.sloc import code_lines, count_in_span
from sloptools.merge import levels


@dataclass(frozen=True)
class Root:
    label: str     # unique name used in reports
    path: Path


@dataclass
class Function:
    root: str
    rel: str            # relative to its root
    qualname: str       # Class.method, outer.inner
    lo: int             # first line, decorators included
    hi: int
    sloc: int
    is_method: bool
    statements: int     # meaningful statements, see levels.meaningful_statements
    n0: str
    n1: str
    prepared: ast.AST

    @property
    def span(self) -> tuple[str, str, int, int]:
        return (self.root, self.rel, self.lo, self.hi)


def label_roots(paths: list[Path]) -> list[Root]:
    """One distinct label per root, from its directory name."""
    taken: set[str] = set()
    out = []
    for p in paths:
        label, n = p.name or "root", 2
        while label in taken:
            label, n = f"{p.name}-{n}", n + 1
        taken.add(label)
        out.append(Root(label, p))
    return out


def functions_in(tree: ast.Module, src: str, root: str, rel: str) -> list[Function]:
    lines = code_lines(src, tree)
    out: list[Function] = []

    def walk(nodes, prefix: str, in_class: bool) -> None:
        for n in nodes:
            if isinstance(n, ast.ClassDef):
                walk(n.body, f"{prefix}{n.name}.", True)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lo = min([n.lineno] + [d.lineno for d in n.decorator_list])
                hi = n.end_lineno or n.lineno
                prepared = levels.prepare(n)
                out.append(Function(
                    root=root, rel=rel, qualname=f"{prefix}{n.name}", lo=lo, hi=hi,
                    sloc=count_in_span(lines, lo, hi), is_method=in_class,
                    statements=levels.meaningful_statements(prepared),
                    n0=levels.n0_hash(prepared), n1=levels.n1_hash(prepared), prepared=prepared))
                walk(n.body, f"{prefix}{n.name}.", False)
            else:
                # defs inside if/try/with blocks at this level
                for field in ("body", "orelse", "finalbody"):
                    sub = getattr(n, field, None)
                    if isinstance(sub, list):
                        walk(sub, prefix, in_class)
                for h in (getattr(n, "handlers", None) or []) + (getattr(n, "cases", None) or []):
                    walk(h.body, prefix, in_class)

    walk(tree.body, "", False)
    return out


def collect(roots: list[Root], excludes: tuple[str, ...], include_tests: bool) -> tuple[list[Function], dict[str, int], list[str]]:
    """Every function under every root, the number of files scanned per root,
    and warnings for files that couldn't be read or parsed."""
    functions: list[Function] = []
    files: dict[str, int] = {}
    warnings: list[str] = []
    for root in roots:
        rels = list_python_files(root.path, excludes, include_tests)
        files[root.label] = len(rels)
        for rel in rels:
            try:
                src = (root.path / rel).read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src)
            except (OSError, SyntaxError, ValueError, RecursionError) as e:
                warnings.append(f"{root.label}:{rel}: skipped ({type(e).__name__})")
                continue
            functions.extend(functions_in(tree, src, root.label, rel))
    return functions, files, warnings
