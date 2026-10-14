"""Roots, and the units of code inside them that can be duplicated.

A unit is a function (or method); a block, a run of statements inside any
body, found from `Body` records, one per statement list in a file (see
blocks.py); a constant table (see constants.py); or a class (classes.py).
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sloptools.common.discover import list_python_files
from sloptools.common.sloc import code_lines, count_in_span
from sloptools.merge import boilerplate, levels
from sloptools.merge.classes import fields_of


@dataclass(frozen=True)
class Root:
    label: str     # unique name used in reports
    path: Path


@dataclass
class Unit:
    kind: str           # "function", "block", "constant" or "class"
    root: str
    rel: str            # relative to its root
    qualname: str       # Class.method, outer.inner; for a block, where it is ("<module>" at top level)
    lo: int             # first line, decorators included
    hi: int
    sloc: int
    is_method: bool     # a method, or (for a block) inside one
    statements: int     # meaningful statements, see levels.meaningful_count
    n0: str
    n1: str
    nodes: list         # [the function], or the block's statements
    seq: list[levels.Elem]
    boilerplate: str | None = None   # why it's not a unit (see boilerplate.reason)
    fields: dict | None = None       # a class's fields: name -> type or None (see classes.fields_of)

    @property
    def span(self) -> tuple[str, str, int, int]:
        return (self.root, self.rel, self.lo, self.hi)

    def bound_names(self) -> set[str]:
        own = self.nodes[0] if self.kind == "function" else None
        return levels.bound_names(self.nodes, own)


@dataclass
class Body:
    """One statement list (a module, class, function or nested body), cut
    at imports, with what block matching needs per statement."""
    root: str
    rel: str
    qualname: str
    is_method: bool
    in_function: bool           # inside a function, not directly in a module or class body
    stmts: list
    n0: list[str]
    n1: list[str]
    weight: list[int]           # meaningful statements in each
    lines: tuple[int, ...]      # the file's code lines, for SLOC

    def first_line(self, i: int) -> int:
        st = self.stmts[i]
        return min([st.lineno] + [d.lineno for d in getattr(st, "decorator_list", [])])

    def unit(self, i: int, j: int) -> Unit:
        """The block stmts[i:j]."""
        lo, hi = self.first_line(i), self.stmts[j - 1].end_lineno or self.stmts[j - 1].lineno
        stmts = self.stmts[i:j]
        return Unit(kind="block", root=self.root, rel=self.rel, qualname=self.qualname, lo=lo, hi=hi,
                    sloc=count_in_span(self.lines, lo, hi), is_method=self.is_method,
                    statements=sum(self.weight[i:j]), n0="|".join(self.n0[i:j]), n1="|".join(self.n1[i:j]),
                    nodes=stmts, seq=levels.block_sequence(stmts))


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


_LIST_FIELDS = ("body", "orelse", "finalbody")


_BREAKS = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _segments(stmts: list) -> list[list]:
    """A statement list without docstrings and no-op statements, cut into
    runs at imports (a run of imports is never a block worth extracting)
    and at defs and classes (they are units of their own)."""
    out, cur = [], []
    for st in stmts:
        if isinstance(st, _BREAKS):
            if cur:
                out.append(cur)
            cur = []
        elif isinstance(st, ast.stmt) and not levels._skippable(st) and not levels._is_docstring(st):
            cur.append(st)
    if cur:
        out.append(cur)
    return out


def units_in(tree: ast.Module, lines: tuple[int, ...], root: str,
             rel: str) -> tuple[list[Unit], list[Body], list[Unit]]:
    """Every function, statement list and class in a file. `lines` are the
    file's code lines (common.sloc.code_lines)."""
    functions: list[Unit] = []
    bodies: list[Body] = []
    classes: list[Unit] = []

    def body(stmts: list, where: str, is_method: bool, in_function: bool = True) -> None:
        for seg in _segments(stmts):
            hashes = [levels.statement_hashes(st) for st in seg]
            bodies.append(Body(root, rel, where, is_method, in_function, seg, [h[0] for h in hashes],
                               [h[1] for h in hashes], [levels.meaningful_count([st]) for st in seg], lines))

    def walk(nodes, prefix: str, in_class: bool, where: str, in_method: bool, inside: bool = False) -> None:
        """`prefix` names defs found here; `where` names the enclosing scope;
        `inside` is whether that scope is a function."""
        for n in nodes:
            if isinstance(n, ast.ClassDef):
                lo = min([n.lineno] + [d.lineno for d in n.decorator_list])
                hi = n.end_lineno or n.lineno
                classes.append(Unit(kind="class", root=root, rel=rel, qualname=f"{prefix}{n.name}", lo=lo, hi=hi,
                                    sloc=count_in_span(lines, lo, hi), is_method=False, statements=0,
                                    n0="", n1="", nodes=[n], seq=[], fields=fields_of(n)))
                body(n.body, f"{prefix}{n.name}", False, in_function=False)
                walk(n.body, f"{prefix}{n.name}.", True, f"{prefix}{n.name}", False, False)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lo = min([n.lineno] + [d.lineno for d in n.decorator_list])
                hi = n.end_lineno or n.lineno
                qualname = f"{prefix}{n.name}"
                reason = boilerplate.reason(n, in_class)
                functions.append(Unit(
                    kind="function", root=root, rel=rel, qualname=qualname, lo=lo, hi=hi,
                    sloc=count_in_span(lines, lo, hi), is_method=in_class,
                    statements=levels.meaningful_statements(n),
                    n0=levels.n0_hash(n), n1=levels.n1_hash(n), nodes=[n], seq=levels.sequence(n),
                    boilerplate=reason))
                if not reason:       # a boilerplate body is boilerplate as a block too
                    body(n.body, qualname, in_class)
                walk(n.body, f"{qualname}.", False, qualname, in_class, True)
            else:
                # compound statements: their bodies are statement lists too, and may hold defs
                subs = [getattr(n, f) for f in _LIST_FIELDS if isinstance(getattr(n, f, None), list)]
                subs += [h.body for h in (getattr(n, "handlers", None) or []) + (getattr(n, "cases", None) or [])]
                for sub in subs:
                    body(sub, where, in_method, in_function=inside)
                    walk(sub, prefix, in_class, where, in_method, inside)

    body(tree.body, "<module>", False, in_function=False)
    walk(tree.body, "", False, "<module>", False)
    return functions, bodies, classes


@dataclass
class Scan:
    functions: list[Unit]                     # function units: boilerplate left out
    bodies: list[Body]                        # statement lists, for blocks
    constants: list[Unit]                     # literal tables
    classes: list[Unit]
    files: dict[str, int]                     # files scanned, per root
    warnings: list[str] = field(default_factory=list)
    generated: list[str] = field(default_factory=list)       # "root:file" skipped as generated
    boilerplate: Counter = field(default_factory=Counter)    # reason -> functions left out


def collect(roots: list[Root], excludes: tuple[str, ...], include_tests: bool) -> Scan:
    """Every function and statement list under every root that could be
    part of a duplicate."""
    from sloptools.merge.constants import constants_in   # it builds on Unit, defined here

    scan = Scan(functions=[], bodies=[], constants=[], classes=[], files={})
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
            lines = code_lines(src, tree)
            functions, bodies, classes = units_in(tree, lines, root.label, rel)
            scan.bodies.extend(bodies)
            scan.classes.extend(classes)
            scan.constants.extend(constants_in(tree, root.label, rel, lines))
            for f in functions:
                if f.boilerplate:
                    scan.boilerplate[f.boilerplate] += 1
                else:
                    scan.functions.append(f)
    return scan
