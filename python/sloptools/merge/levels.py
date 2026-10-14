"""Normalised forms of a function, at increasing levels of looseness.

N0 (exact) ignores formatting, comments, docstrings, type annotations and
the function's own name and decorators. N1 (renamed) also erases local
identifiers and literal values, but keeps attribute names and the names of
called functions: the same rules as common.normalise.Normaliser, plus the
other places a local name can appear (nested def and class names,
`except ... as`, `global`/`nonlocal`).

For scoring near-copies, a function is also flattened into its N1 statement
sequence: the signature, then every statement in pre-order, each reduced to
its own header (an `if` contributes its test, not its body), with markers
where an `else`, `elif` or `finally` begins. Two statements with the same
key have headers that line up node for node, so their literals and names
can be compared position by position (see `leaves`).

Everything here reads the original tree and never copies or mutates it: one
traversal (`_children`) decides what is skipped, and the hashes, sequence
keys and leaves are all built from it, so they always agree.
"""

from __future__ import annotations

import ast
import hashlib
from typing import Iterator, NamedTuple

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_BODY_FIELDS = ("body", "orelse", "finalbody", "handlers", "cases")
_IGNORED_FIELDS = {"returns", "annotation", "type_comment", "simple"}


def _is_docstring(st: ast.AST) -> bool:
    return isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str)


def _skippable(n: ast.AST) -> bool:
    """`pass`, `...` and bare `return`: they carry no logic."""
    return (isinstance(n, ast.Pass) or (isinstance(n, ast.Return) and n.value is None)
            or (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and n.value.value is Ellipsis))


def _children(n: ast.AST, root: ast.AST, header: ast.AST | None) -> Iterator[tuple[str, object]]:
    """(field, value) pairs of `n` that the normalised forms look at.

    Skips type annotations, the root function's decorators, and docstrings;
    `x: int = 1` is read as `x = 1`. When `n` is `header`, its nested bodies
    are left out.
    """
    if isinstance(n, ast.AnnAssign) and n.value is not None:
        yield "targets", [n.target]
        yield "value", n.value
        return
    for f in n._fields:
        if f in _IGNORED_FIELDS or (f == "decorator_list" and n is root):
            continue
        if n is header and f in _BODY_FIELDS:
            continue
        v = getattr(n, f, None)
        if f == "body" and isinstance(n, _DEFS) and v and _is_docstring(v[0]):
            v = v[1:]
        yield f, v


def _type_name(n: ast.AST) -> str:
    return "Assign" if isinstance(n, ast.AnnAssign) and n.value is not None else type(n).__name__


def _serialise(n: object, root: ast.AST, header: ast.AST | None, rename: bool, out: list) -> None:
    if isinstance(n, list):
        out.append("[")
        for x in n:
            _serialise(x, root, header, rename, out)
            out.append(",")
        out.append("]")
        return
    if not isinstance(n, ast.AST):
        out.append(repr(n))
        return
    if rename:
        if isinstance(n, ast.Name):
            out.append(f"Name(V,{type(n.ctx).__name__})")
            return
        if isinstance(n, ast.Constant):
            out.append("Constant(C)")
            return
        if isinstance(n, ast.arg):
            out.append("arg(V)")
            return
    out.append(_type_name(n) + "(")
    for f, v in _children(n, root, header):
        out.append(f + "=")
        if n is root and f == "name":
            out.append("F")
        elif rename and f == "name" and isinstance(v, str) and isinstance(n, (*_DEFS, ast.ExceptHandler)):
            out.append("V")
        elif rename and f == "names" and isinstance(n, (ast.Global, ast.Nonlocal)):
            out.append(str(len(v)))
        elif rename and f == "func" and isinstance(v, ast.Name):
            out.append(f"Name({v.id})")        # called names are kept
        else:
            _serialise(v, root, header, rename, out)
        out.append(";")
    out.append(")")


def _digest(n: ast.AST, root: ast.AST, header: ast.AST | None, rename: bool) -> str:
    out: list = []
    _serialise(n, root, header, rename, out)
    return hashlib.md5("".join(out).encode()).hexdigest()[:16]


def n0_hash(fn: ast.AST) -> str:
    return _digest(fn, fn, None, False)


def n1_hash(fn: ast.AST) -> str:
    return _digest(fn, fn, None, True)


def _statements(stmts: list) -> list:
    return [s for s in stmts if isinstance(s, ast.stmt) and not _skippable(s)]


def _body(n: ast.AST) -> list:
    body = getattr(n, "body", None) or []
    if isinstance(n, _DEFS) and body and _is_docstring(body[0]):
        body = body[1:]
    return body


def _nested(n: ast.AST) -> list[list]:
    """The statement lists directly inside `n`, docstrings dropped."""
    lists = [_body(n), getattr(n, "orelse", None) or [], getattr(n, "finalbody", None) or []]
    lists += [h.body for h in (getattr(n, "handlers", None) or []) + (getattr(n, "cases", None) or [])]
    return lists


def meaningful_count(stmts: list) -> int:
    """Statements in `stmts`, at any depth, not counting docstrings, `pass`,
    `...` and bare `return`."""
    return sum(1 + sum(meaningful_count(sub) for sub in _nested(s)) for s in _statements(stmts))


def meaningful_statements(fn: ast.AST) -> int:
    return meaningful_count(_body(fn))


def statement_hashes(st: ast.stmt) -> tuple[str, str]:
    """(N0, N1) hash of one whole statement, nested bodies included."""
    return _digest(st, None, None, False), _digest(st, None, None, True)


def bound_names(nodes: list[ast.AST], own: ast.AST | None = None) -> set[str]:
    """Names the code binds itself: parameters, assignment and loop targets,
    nested defs, `except ... as`, imports. `own` is the function whose own
    name doesn't count (it's bound by the code around it)."""
    out: set[str] = set()
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n, ast.arg):
                out.add(n.arg)
            elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                out.add(n.id)
            elif isinstance(n, _DEFS) and n is not own:
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


class Elem(NamedTuple):
    """One entry of a statement sequence."""
    key: str                  # hash of the normalised header; equal keys line up
    lo: int
    hi: int
    node: ast.AST | None      # the statement (only its header counts); None for markers
    root: ast.AST | None      # the function the sequence belongs to


def _header_end(n: ast.AST) -> int:
    """Last line of a statement's own header, before its first nested body."""
    firsts = [sub[0].lineno for sub in _nested(n) if sub and hasattr(sub[0], "lineno")]
    return max(n.lineno, min(firsts) - 1) if firsts else (getattr(n, "end_lineno", None) or n.lineno)


def sequence(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[Elem]:
    """The N1 statement sequence of a function, starting with its signature."""
    return _flatten([fn], fn)


def block_sequence(stmts: list) -> list[Elem]:
    """The N1 statement sequence of a run of statements."""
    return _flatten(_statements(stmts), None)


def _flatten(nodes: list, fn: ast.AST | None) -> list[Elem]:
    out: list[Elem] = []

    def add(n: ast.AST) -> None:
        lo = getattr(n, "lineno", None) or (out[-1].hi if out else nodes[0].lineno)
        hi = _header_end(n) if hasattr(n, "lineno") else lo
        out.append(Elem(_digest(n, fn, n, True), lo, hi, n, fn))

    def marker(name: str, first: ast.AST) -> None:
        out.append(Elem(f"<{name}>", first.lineno, first.lineno, None, None))

    def visit(n: ast.AST) -> None:
        add(n)
        for st in _statements(_body(n)):
            visit(st)
        for h in (getattr(n, "handlers", None) or []) + (getattr(n, "cases", None) or []):
            visit(h)
        orelse = _statements(getattr(n, "orelse", None) or [])
        if orelse:
            elif_ = isinstance(n, ast.If) and len(n.orelse) == 1 and isinstance(n.orelse[0], ast.If)
            marker("elif" if elif_ else "else", orelse[0])
            for st in orelse:
                visit(st)
        finalbody = _statements(getattr(n, "finalbody", None) or [])
        if finalbody:
            marker("finally", finalbody[0])
            for st in finalbody:
                visit(st)

    for n in nodes:
        visit(n)
    return out


def _walk(n: object, root: ast.AST, header: ast.AST | None) -> Iterator[ast.AST]:
    """Nodes in the order _serialise reads them, with the same skips."""
    if isinstance(n, list):
        for x in n:
            yield from _walk(x, root, header)
        return
    if not isinstance(n, ast.AST):
        return
    yield n
    for f, v in _children(n, root, header):
        if not (f == "func" and isinstance(v, ast.Name)):
            yield from _walk(v, root, header)


def leaves(elem: Elem) -> list[Leaf]:
    """The literals and names in a statement's header, in a fixed order.
    Headers with equal keys give equally long lists that line up."""
    if elem.node is None:
        return []
    out = []
    for n in _walk(elem.node, elem.root, elem.node):
        line = getattr(n, "lineno", None)
        if isinstance(n, ast.Constant):
            out.append(Leaf("literal", n.value, line))
        elif isinstance(n, ast.Name):
            out.append(Leaf("name", n.id, line))
        elif isinstance(n, ast.arg):
            out.append(Leaf("name", n.arg, line))
    return out
