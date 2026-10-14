"""Constant tables: the same literal list, tuple, set or dict in several places.

Column lists, choice tables, config maps: usually a missing shared constant.
A constant is any list, tuple, set or dict literal built only from constants
(nested literals included, so `[("a", "A"), ("b", "B")]` counts), with at
least three distinct elements. Only the outermost literal counts.

Its forms, for matching like functions:

- N0 is the whole value. Lists and tuples compare in order; sets and dicts
  ignore order.
- N1 is the structure: for a dict its keys, for anything else its value. So
  dicts with the same keys and different values are `renamed` copies, and
  their differing values are reported as parameters.
- Its elements (a dict's keys) are what `near` copies are scored on: IDF-
  weighted overlap, 2 * W(shared) / (W(a) + W(b)), so sharing rare entries
  counts for more than sharing "id" and "name". Near copies must share at
  least three entries.
"""

from __future__ import annotations

import ast
import hashlib
from collections import Counter

from sloptools.common.sloc import count_in_span
from sloptools.merge.units import Unit

MIN_DISTINCT = 3
_CONTAINERS = (ast.List, ast.Tuple, ast.Set, ast.Dict)


def _value(n: ast.AST) -> object | None:
    """A hashable, order-normalised form of a literal, or None if `n` isn't one."""
    if isinstance(n, ast.Constant):
        return (type(n.value).__name__, n.value)
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)) and isinstance(n.operand, ast.Constant):
        v = _value(n.operand)
        return ("neg" if isinstance(n.op, ast.USub) else "pos", v)
    if isinstance(n, (ast.List, ast.Tuple)):
        elts = [_value(e) for e in n.elts]
        return None if None in elts else ("seq", tuple(elts))
    if isinstance(n, ast.Set):
        elts = [_value(e) for e in n.elts]
        return None if None in elts else ("set", tuple(sorted(elts, key=repr)))
    if isinstance(n, ast.Dict):
        if any(k is None for k in n.keys):     # **spread
            return None
        items = [(_value(k), _value(v)) for k, v in zip(n.keys, n.values)]
        return None if any(None in kv for kv in items) else ("dict", tuple(sorted(items, key=repr)))
    return None


def _h(v: object) -> str:
    return hashlib.md5(repr(v).encode()).hexdigest()[:16]


def elements(n: ast.AST) -> list[str]:
    """What near copies are scored on: the entries, or a dict's keys."""
    if isinstance(n, ast.Dict):
        return [repr(_value(k)) for k in n.keys]
    return [repr(_value(e)) for e in n.elts]


def _target(t: ast.AST) -> str | None:
    if isinstance(t, ast.Name):
        return t.id
    if isinstance(t, ast.Attribute):
        return t.attr
    return None


def constants_in(tree: ast.Module, root: str, rel: str, lines: tuple[int, ...]) -> list[Unit]:
    out: list[Unit] = []

    def add(n: ast.AST, where: str, name: str | None, is_method: bool) -> None:
        v = _value(n)
        if v is None or len(set(elements(n))) < MIN_DISTINCT:
            return
        if name and name.startswith("__") and name.endswith("__"):    # __all__, __slots__
            return
        n1 = ("dict-keys", tuple(k for k, _ in v[1])) if isinstance(n, ast.Dict) else v
        lo, hi = n.lineno, n.end_lineno or n.lineno
        qualname = f"{where}.{name}" if name and where != "<module>" else (name or where)
        out.append(Unit(kind="constant", root=root, rel=rel, qualname=qualname, lo=lo, hi=hi,
                        sloc=max(1, count_in_span(lines, lo, hi)), is_method=is_method, statements=0,
                        n0=_h(v), n1=_h(n1), nodes=[n], seq=[]))

    def visit(n: ast.AST, where: str, is_method: bool, in_class: bool) -> None:
        if isinstance(n, ast.ClassDef):
            inner = n.name if where == "<module>" else f"{where}.{n.name}"
            for c in ast.iter_child_nodes(n):
                visit(c, inner, False, True)
            return
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inner = n.name if where == "<module>" else f"{where}.{n.name}"
            for c in ast.iter_child_nodes(n):
                visit(c, inner, in_class, False)
            return
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and isinstance(n.value, _CONTAINERS):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            names = [t for t in map(_target, targets) if t]
            if _value(n.value) is not None:
                add(n.value, where, names[0] if len(names) == 1 else None, is_method)
                return                  # its inner literals are part of it
        if isinstance(n, _CONTAINERS) and _value(n) is not None:
            add(n, where, None, is_method)
            return
        for c in ast.iter_child_nodes(n):
            visit(c, where, is_method, in_class)

    visit(tree, "<module>", False, False)
    return out


def score(a: Unit, b: Unit, w: dict[str, float]) -> float:
    """Weighted overlap; 0 unless they share at least MIN_DISTINCT entries
    (two 3-tuples sharing two values aren't copies of one table)."""
    ea, eb = Counter(elements(a.nodes[0])), Counter(elements(b.nodes[0]))
    if sum((ea & eb).values()) < MIN_DISTINCT:
        return 0.0
    shared = sum(w[k] * min(c, eb[k]) for k, c in ea.items() if k in eb)
    denom = sum(w[k] * c for k, c in ea.items()) + sum(w[k] * c for k, c in eb.items())
    return 2 * shared / denom if denom else 0.0


def _readable(e: str) -> object:
    """An element key back as a plain value, for the report."""
    v = ast.literal_eval(e)
    if isinstance(v, tuple) and len(v) == 2 and v[0] in ("str", "int", "float", "bool", "NoneType"):
        return v[1]
    return repr(v)


def differences(members: list[Unit], ids: list[str], medoid: int) -> list[dict]:
    """For each member, the entries it has that the medoid lacks ("added")
    and the medoid's entries it lacks ("removed")."""
    out = []
    base = Counter(elements(members[medoid].nodes[0]))
    for k, m in enumerate(members):
        if k == medoid:
            continue
        mine = Counter(elements(m.nodes[0]))
        for change, diff in (("added", mine - base), ("removed", base - mine)):
            if diff:
                out.append({"member": ids[k], "change": change,
                            "values": [_readable(e) for e in sorted(diff.elements(), key=repr)]})
    return out


def parameters(members: list[Unit], ids: list[str]) -> list[dict]:
    """For dicts with the same keys: the keys whose values differ."""
    if not all(isinstance(m.nodes[0], ast.Dict) for m in members):
        return []
    by_key = [{repr(_value(k)): v for k, v in zip(m.nodes[0].keys, m.nodes[0].values)} for m in members]
    out = []
    for key in by_key[0]:
        vals = [d.get(key) for d in by_key]
        if any(v is None for v in vals):
            continue
        reprs = [repr(_value(v)) for v in vals]
        if len(set(reprs)) > 1:
            out.append({"kind": "literal", "key": _readable(key),
                        "values": {i: _readable(r) for i, r in zip(ids, reprs)},
                        "lines": {i: v.lineno for i, v in zip(ids, vals)}, "count": 1})
    return out
