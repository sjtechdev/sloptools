"""Duplicated blocks: the same run of statements in several places.

These are "extract a helper" candidates: logic copied into otherwise
different functions. Matching is by hash, like the exact and renamed
function tiers, so no such block is missed:

1. In every statement list, each position seeds the shortest run starting
   there that holds at least `min_statements` meaningful statements (one
   big duplicated loop counts, not only runs of three one-liners).
2. Runs with equal N1 hashes, found in two or more places that don't
   overlap, are a candidate group.
3. The group is extended statement by statement, forwards and backwards,
   as long as every copy still agrees, giving maximal blocks.

A block group is dropped if it is only plain stores (`self.x = x`,
`aliases = ['mips']`) and import guards (`try: import x / except
ImportError: ...`), if it is only assignments at module or class level
(declarations, whatever the values), if its copies are back to back in one
statement list,
if none of its statements is distinctive (see match._distinctive), or (in
match.py) if every copy sits inside members of one function group.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from typing import Callable

from sloptools.merge import levels
from sloptools.merge.units import Body, Unit

Occurrence = tuple[int, int, int]    # (body index, start, end)


def _windows(bodies: list[Body], min_statements: int) -> dict[tuple, list[Occurrence]]:
    out: dict[tuple, list[Occurrence]] = defaultdict(list)
    for b, body in enumerate(bodies):
        n, j, total = len(body.stmts), 0, 0
        for i in range(n):
            while j < n and total < min_statements:
                total += body.weight[j]
                j += 1
            if total < min_statements:
                break
            out[tuple(body.n1[i:j])].append((b, i, j))
            total -= body.weight[i]
    return out


def _disjoint(occs: list[Occurrence]) -> list[Occurrence]:
    """Drop occurrences overlapping an earlier one in the same body: a run
    repeated back to back (`x = 0` four times) isn't two copies."""
    out, last_end = [], {}
    for b, i, j in sorted(occs):
        if i >= last_end.get(b, -1):
            out.append((b, i, j))
            last_end[b] = j
    return out


def _fits(occs: list[Occurrence]) -> bool:
    ends: dict[int, int] = {}
    for b, i, j in sorted(occs):
        if i < ends.get(b, -1):
            return False
        ends[b] = j
    return True


def _extend(bodies: list[Body], occs: list[Occurrence]) -> list[Occurrence]:
    while True:      # forwards
        nxt = [(b, i, j + 1) for b, i, j in occs]
        if all(j <= len(bodies[b].stmts) for b, _, j in nxt) \
                and len({bodies[b].n1[j - 1] for b, _, j in nxt}) == 1 and _fits(nxt):
            occs = nxt
        else:
            break
    while True:      # backwards
        prv = [(b, i - 1, j) for b, i, j in occs]
        if all(i >= 0 for _, i, _ in prv) and len({bodies[b].n1[i] for b, i, _ in prv}) == 1 and _fits(prv):
            occs = prv
        else:
            break
    return sorted(occs)


def _repetition(occs: list[Occurrence]) -> bool:
    """All copies back to back in one statement list: `x.push(1)` six times
    is repetition (a loop, maybe), not a block pasted in several places."""
    return len({b for b, _, _ in occs}) == 1 and all(
        prev[2] == nxt[1] for prev, nxt in zip(occs, occs[1:]))


_ASSIGNS = (ast.Assign, ast.AnnAssign, ast.AugAssign)


def _literal(n: ast.AST) -> bool:
    """A constant, or a list/tuple/set/dict built only from constants."""
    if isinstance(n, ast.Constant):
        return True
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
        return _literal(n.operand)
    if isinstance(n, (ast.List, ast.Tuple, ast.Set)):
        return all(_literal(e) for e in n.elts)
    if isinstance(n, ast.Dict):
        return all(k is not None and _literal(k) and _literal(v) for k, v in zip(n.keys, n.values))
    return False


def _import_guard(st: ast.stmt) -> bool:
    """`try: import x / except ImportError: x = None`, `if TYPE_CHECKING:
    from a import B`: an `if` or `try` holding only imports, `pass` and
    plain stores. An idiom, not logic to extract."""
    if not isinstance(st, (ast.If, ast.Try)):
        return False
    inner = list(st.body) + list(st.orelse) + list(getattr(st, "finalbody", []))
    inner += [s for h in getattr(st, "handlers", []) for s in h.body]
    return all(isinstance(s, (ast.Import, ast.ImportFrom, ast.Pass)) or _plain_store(s) or _import_guard(s)
               for s in inner)


def _plain_store(st: ast.stmt) -> bool:
    """Storing a name or a literal: `self.x = x`, `name = 'MIPS'`,
    `aliases = ['mips']`. A run of these is declarations (constant tables
    are matched as their own unit), not logic to extract."""
    if isinstance(st, ast.Assign):
        value, targets = st.value, st.targets
    elif isinstance(st, ast.AnnAssign) and st.value is not None:
        value, targets = st.value, [st.target]
    else:
        return False
    return (isinstance(value, ast.Name) or _literal(value)) \
        and all(isinstance(t, (ast.Name, ast.Attribute)) for t in targets)


def find(bodies: list[Body], min_statements: int,
         distinctive: Callable[[list[levels.Elem]], bool]) -> list[list[Unit]]:
    """Each duplicated block, as its copies (sorted by location)."""
    seen: set[tuple] = set()
    out = []
    for occs in _windows(bodies, min_statements).values():
        occs = _disjoint(occs)
        if len(occs) < 2:
            continue
        occs = _extend(bodies, occs)
        key = tuple(occs)
        if key in seen or _repetition(occs):
            continue
        seen.add(key)
        b, i, j = occs[0]
        stmts = bodies[b].stmts[i:j]
        if all(_plain_store(st) or _import_guard(st) for st in stmts):
            continue
        if not any(bodies[b].in_function for b, _, _ in occs) and all(isinstance(st, _ASSIGNS) for st in stmts):
            continue     # module or class declarations: data, whatever the values
        units = [bodies[b].unit(i, j) for b, i, j in occs]
        if not distinctive(units[0].seq):
            continue
        out.append(units)
    return out
