"""The `related` tier: functions written differently that do the same thing.

A function's N2 form is its vocabulary: a bag of "tokens of intent", the
names it calls (`call:sorted`, `call:.append`), the attributes it uses
(`attr:.state`), the imported modules it uses (`mod:os.path`), its string
literals (`str:active`), and the exceptions it raises and catches
(`raise:KeyError`, `catch:TimeoutError`). Docstrings don't count.

Functions that matched nothing structurally are scored on vocabulary by
IDF-weighted overlap, 2 * W(shared) / (W(a) + W(b)), and must share at least
three tokens and be within 2x of each other in size. These are the lowest-
confidence matches: they use the same things in a similar amount of code.
They are candidates for the skill to read and verify, and the group lists
the vocabulary all its members share as the reason.
"""

from __future__ import annotations

import ast
from collections import Counter

from sloptools.merge import levels
from sloptools.merge.units import Unit

MIN_SHARED = 3
MAX_SIZE_RATIO = 2.0
_MAX_STRING = 60


def _name(n: ast.AST) -> str | None:
    n = n.func if isinstance(n, ast.Call) else n
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Attribute):
        return n.attr
    return None


def vocabulary(fn: Unit) -> list[str]:
    node = fn.nodes[0]
    imports = fn.module.imports if fn.module else {}
    tokens: list[str] = []
    callees: set[int] = set()
    for st in levels._body(node):
        for n in ast.walk(st):
            if isinstance(n, ast.Call):
                callees.add(id(n.func))
                if isinstance(n.func, ast.Name):
                    tokens.append(f"call:{n.func.id}")
                elif isinstance(n.func, ast.Attribute):
                    tokens.append(f"call:.{n.func.attr}")
            elif isinstance(n, ast.Attribute) and id(n) not in callees:
                tokens.append(f"attr:.{n.attr}")
            elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in imports:
                tokens.append(f"mod:{imports[n.id]}")
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and 0 < len(n.value) <= _MAX_STRING:
                tokens.append(f"str:{n.value}")
            elif isinstance(n, ast.Raise) and n.exc is not None and (name := _name(n.exc)):
                tokens.append(f"raise:{name}")
            elif isinstance(n, ast.ExceptHandler) and n.type is not None:
                kinds = n.type.elts if isinstance(n.type, ast.Tuple) else [n.type]
                tokens += [f"catch:{name}" for k in kinds if (name := _name(k))]
    return tokens


def score(a: list[str], b: list[str], size_a: int, size_b: int, w: dict[str, float]) -> float:
    if max(size_a, size_b) > MAX_SIZE_RATIO * max(1, min(size_a, size_b)):
        return 0.0
    ca, cb = Counter(a), Counter(b)
    if sum((ca & cb).values()) < MIN_SHARED:
        return 0.0
    shared = sum(w[k] * min(c, cb[k]) for k, c in ca.items() if k in cb)
    denom = sum(w[k] * c for k, c in ca.items()) + sum(w[k] * c for k, c in cb.items())
    return 2 * shared / denom if denom else 0.0


def shared_vocabulary(members: list[Unit]) -> list[str]:
    common = Counter(vocabulary(members[0]))
    for m in members[1:]:
        common &= Counter(vocabulary(m))
    return sorted(common)
