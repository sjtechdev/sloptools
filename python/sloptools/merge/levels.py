"""Normalised forms of a function, at increasing levels of looseness.

N0 (exact) erases formatting, comments, docstrings, type annotations and
decorators. N1 (renamed) also erases local identifiers and literal values,
but keeps attribute names and the names of called functions (see
common.normalise). Two functions with equal N1 forms are the same code
modulo renames and literals, and their prepared trees line up node for node,
which is what `differing_leaves` relies on.
"""

from __future__ import annotations

import ast
import copy
import hashlib
from typing import Iterator, NamedTuple

from sloptools.common.normalise import Normaliser

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _is_docstring(st: ast.stmt) -> bool:
    return isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str)


class _StripAnnotations(ast.NodeTransformer):
    """`x: int = 1` becomes `x = 1`; a bare `x: int` declaration stays, with
    its annotation erased."""

    def visit_AnnAssign(self, n: ast.AnnAssign) -> ast.stmt:
        if n.value is None:
            n.annotation = ast.Constant(value=None)
            return n
        return ast.copy_location(ast.Assign(targets=[n.target], value=n.value), n)


def prepare(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.AST:
    """A copy of `fn` with everything N0 ignores removed: its own name,
    decorators, docstrings (its own and nested ones) and type annotations."""
    fn = _StripAnnotations().visit(copy.deepcopy(fn))
    fn.name, fn.decorator_list = "F", []
    for n in ast.walk(fn):
        if isinstance(n, _DEFS) and n.body and _is_docstring(n.body[0]):
            n.body = n.body[1:] or [ast.Pass()]
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            n.returns = None
        elif isinstance(n, ast.arg):
            n.annotation = None
    return fn


class _RenameNormaliser(Normaliser):
    """common.normalise.Normaliser, plus the other places a local name can
    appear that it doesn't cover (it was written for function bodies)."""

    def visit_FunctionDef(self, n):
        n.name = "V"
        return self.generic_visit(n)

    visit_AsyncFunctionDef = visit_ClassDef = visit_FunctionDef

    def visit_ExceptHandler(self, n):
        if n.name:
            n.name = "V"
        return self.generic_visit(n)

    def visit_Global(self, n):
        n.names = ["V"] * len(n.names)
        return n

    visit_Nonlocal = visit_Global


def _digest(tree: ast.AST) -> str:
    return hashlib.md5(ast.dump(tree).encode()).hexdigest()[:16]


def n0_hash(prepared: ast.AST) -> str:
    return _digest(prepared)


def n1_hash(prepared: ast.AST) -> str:
    return _digest(_RenameNormaliser().visit(copy.deepcopy(prepared)))


def meaningful_statements(prepared: ast.AST) -> int:
    """Statements in the body, at any depth, not counting `pass`, `...` and
    bare `return` (docstrings are already gone)."""
    count = 0
    for n in ast.walk(prepared):
        if n is prepared or not isinstance(n, ast.stmt):
            continue
        if isinstance(n, ast.Pass) or (isinstance(n, ast.Return) and n.value is None):
            continue
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and n.value.value is Ellipsis:
            continue
        count += 1
    return count


def bound_names(prepared: ast.AST) -> set[str]:
    """Names the function binds itself: parameters, assignment and loop
    targets, nested defs, `except ... as`, imports."""
    out: set[str] = set()
    for n in ast.walk(prepared):
        if isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, _DEFS) and n is not prepared:
            out.add(n.name)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            out.update((a.asname or a.name).split(".")[0] for a in n.names)
    return out


class Leaf(NamedTuple):
    kind: str          # "literal" or "name"
    value: object
    line: int | None


def _leaf(n: ast.AST) -> Leaf | None:
    line = getattr(n, "lineno", None)
    if isinstance(n, ast.Constant):
        return Leaf("literal", n.value, line)
    if isinstance(n, ast.Name):
        return Leaf("name", n.id, line)
    if isinstance(n, ast.arg):
        return Leaf("name", n.arg, line)
    return None


def leaves(prepared: ast.AST) -> Iterator[Leaf | None]:
    """One entry per node, in a fixed order; the literal or name it holds,
    or None. Equal-N1 functions give equally long sequences that line up."""
    for n in ast.walk(prepared):
        yield _leaf(n)
