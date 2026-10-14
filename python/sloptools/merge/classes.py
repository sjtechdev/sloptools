"""Classes that duplicate each other, by their fields, their methods, or both.

A class is reduced to a profile: one token per declared field (`f:email`)
and one per method that is in a function group (`m:<group>`). A method that
matches nothing elsewhere gets a token of its own, so it counts against the
match. Two classes are scored on their profiles by IDF-weighted overlap,
2 * W(shared) / (W(a) + W(b)), and must share at least three tokens, or
two matching methods (each already a confirmed copy, so stronger evidence
than two common field names). This covers both kinds of class match in one
score:

- data shape: dataclasses, Pydantic models, TypedDicts or plain records
  declaring the same fields;
- behaviour: classes whose methods mostly match pairwise (a base class or
  mixin waiting to be extracted).

Fields are annotated class attributes (`email: str`), class attributes
assigned a call (`email = models.CharField(...)`, as in Django or
SQLAlchemy), and `self.<name>` assigned in `__init__`. Plain class
attributes assigned a literal (`name = "MIPS"`) are configuration, not
fields: counting them would make every pygments lexer match every other.

Shapes, for the tiers: N1 is the profile, so classes with the same fields
and the same matching methods are `exact` or `renamed`; N0 adds the field
types and the methods' own N0 forms, so `exact` means identical types and
verbatim methods.
"""

from __future__ import annotations

import ast
import hashlib
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:       # units.py imports fields_of from here
    from sloptools.merge.units import Unit

MIN_SHARED = 3              # tokens two classes must share...
MIN_SHARED_METHODS = 2      # ...unless this many are matching methods, already confirmed copies


def fields_of(cls: ast.ClassDef) -> dict[str, str | None]:
    """Field name -> its type (annotation, or the field constructor called),
    in declaration order; None where untyped."""
    out: dict[str, str | None] = {}
    for st in cls.body:
        if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
            if not (isinstance(st.annotation, ast.Name) and st.annotation.id == "ClassVar") \
                    and not ast.unparse(st.annotation).startswith(("ClassVar", "typing.ClassVar")):
                out.setdefault(st.target.id, ast.unparse(st.annotation))
        elif isinstance(st, ast.Assign) and isinstance(st.value, ast.Call):
            for t in st.targets:
                if isinstance(t, ast.Name) and not t.id.startswith("__"):
                    out.setdefault(t.id, ast.unparse(st.value.func))
    init = next((st for st in cls.body if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and st.name == "__init__"), None)
    if init and (init.args.posonlyargs + init.args.args):
        me = (init.args.posonlyargs + init.args.args)[0].arg
        for n in ast.walk(init):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else []
            for t in targets:
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == me:
                    out.setdefault(t.attr, ast.unparse(n.annotation) if isinstance(n, ast.AnnAssign) else None)
    return out


def _h(v: object) -> str:
    return hashlib.md5(repr(v).encode()).hexdigest()[:16]


def method_token(m: Unit, group_of: dict[int, int]) -> str:
    g = group_of.get(id(m))
    return f"m:{g}" if g is not None else f"u:{m.root}:{m.rel}:{m.qualname}"


def profile(cls: Unit, methods: list[Unit], group_of: dict[int, int]) -> list[str]:
    """The class's tokens: fields, then methods (by group, or on their own)."""
    return [f"f:{name}" for name in cls.fields] + [method_token(m, group_of) for m in methods]


def set_forms(cls: Unit, methods: list[Unit], group_of: dict[int, int]) -> list[str]:
    """Fill in the class unit's N0/N1 from its profile; return the profile."""
    tokens = profile(cls, methods, group_of)
    # a method matching nothing has a token of its own, so a class with one
    # is never the same shape as another class
    cls.n1 = _h(sorted(tokens))
    cls.n0 = _h((sorted(tokens), sorted(cls.fields.items(), key=lambda kv: kv[0]),
                 sorted(m.n0 for m in methods)))
    return tokens


def enough(tokens: list[str]) -> bool:
    """Could this profile meet the sharing floor at all?"""
    return len(tokens) >= MIN_SHARED or sum(t.startswith("m:") for t in tokens) >= MIN_SHARED_METHODS


def score(a: list[str], b: list[str], w: dict[str, float]) -> float:
    ca, cb = Counter(a), Counter(b)
    both = ca & cb
    if sum(both.values()) < MIN_SHARED and sum(c for t, c in both.items() if t.startswith("m:")) < MIN_SHARED_METHODS:
        return 0.0
    shared = sum(w[k] * min(c, cb[k]) for k, c in ca.items() if k in cb)
    denom = sum(w[k] * c for k, c in ca.items()) + sum(w[k] * c for k, c in cb.items())
    return 2 * shared / denom if denom else 0.0


def differences(ids: list[str], medoid: int, profiles: list[list[str]],
                method_names: list[dict[str, list[str]]]) -> list[dict]:
    """For each member, the fields and methods it has that the medoid
    lacks ("added"), and the medoid's that it lacks ("removed").
    `method_names[k]` maps member k's method tokens to method names."""
    out = []
    base = Counter(profiles[medoid])
    for k in range(len(profiles)):
        if k == medoid:
            continue
        mine = Counter(profiles[k])
        for change, diff, owner in (("added", mine - base, k), ("removed", base - mine, medoid)):
            if not diff:
                continue
            entry = {"member": ids[k], "change": change}
            fields = sorted(t[2:] for t in diff.elements() if t.startswith("f:"))
            methods = sorted({n for t in diff.elements() if not t.startswith("f:")
                              for n in method_names[owner].get(t, [t])})
            if fields:
                entry["fields"] = fields
            if methods:
                entry["methods"] = methods
            out.append(entry)
    return out


def parameters(members: list[Unit], ids: list[str]) -> list[dict]:
    """Fields all members declare, with types that differ between them."""
    out = []
    for name in members[0].fields:
        if any(name not in m.fields for m in members):
            continue
        types = [m.fields[name] for m in members]
        if len(set(types)) > 1:
            out.append({"kind": "type", "key": name, "values": dict(zip(ids, types)), "count": 1})
    return out
