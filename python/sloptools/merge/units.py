"""Roots, and the units of code inside them that can be duplicated.

Functions and methods for now; blocks, classes and constant tables come in
later milestones.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sloptools.common.discover import list_python_files
from sloptools.common.sloc import code_lines, count_in_span
from sloptools.merge import boilerplate, levels


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
    node: ast.FunctionDef | ast.AsyncFunctionDef
    seq: list[levels.Elem]
    boilerplate: str | None = None   # why it's not a unit (see boilerplate.reason)

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
                out.append(Function(
                    root=root, rel=rel, qualname=f"{prefix}{n.name}", lo=lo, hi=hi,
                    sloc=count_in_span(lines, lo, hi), is_method=in_class,
                    statements=levels.meaningful_statements(n),
                    n0=levels.n0_hash(n), n1=levels.n1_hash(n), node=n, seq=levels.sequence(n),
                    boilerplate=boilerplate.reason(n, in_class)))
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


@dataclass
class Scan:
    functions: list[Function]                 # the units: boilerplate left out
    files: dict[str, int]                     # files scanned, per root
    warnings: list[str] = field(default_factory=list)
    generated: list[str] = field(default_factory=list)       # "root:file" skipped as generated
    boilerplate: Counter = field(default_factory=Counter)    # reason -> functions left out


def collect(roots: list[Root], excludes: tuple[str, ...], include_tests: bool) -> Scan:
    """Every function under every root that could be part of a duplicate."""
    scan = Scan(functions=[], files={})
    for root in roots:
        rels = list_python_files(root.path, excludes, include_tests)
        scan.files[root.label] = len(rels)
        for rel in rels:
            try:
                src = (root.path / rel).read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src)
            except (OSError, SyntaxError, ValueError, RecursionError) as e:
                scan.warnings.append(f"{root.label}:{rel}: skipped ({type(e).__name__})")
                continue
            if boilerplate.generated_file(rel, src, tree):
                scan.generated.append(f"{root.label}:{rel}")
                continue
            for f in functions_in(tree, src, root.label, rel):
                if f.boilerplate:
                    scan.boilerplate[f.boilerplate] += 1
                else:
                    scan.functions.append(f)
    return scan
