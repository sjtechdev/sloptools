"""What a function or block depends on: the evidence for "could this move?"

For each member of a function or block group, the names it reads but
doesn't bind, sorted into:

- imports: names imported at module level, as what they refer to
  (`from sqlalchemy import text` used as `text` is `sqlalchemy.text`);
- globals: other names bound at module level (functions, classes,
  constants);
- self_attrs: attributes of `self` (the method's first parameter, or the
  enclosing method's, for a block) that it reads or writes;
- outer: names from an enclosing function. For a block these are the
  enclosing function's parameters and locals it reads, which is to say the
  parameters an extracted helper would take.

Builtins are left out.
"""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass, field

_BUILTINS = set(dir(builtins))


@dataclass
class ModuleInfo:
    imports: dict[str, str] = field(default_factory=dict)   # local name -> what it refers to
    defined: set[str] = field(default_factory=set)          # other names bound at module level


def module_info(tree: ast.Module) -> ModuleInfo:
    info = ModuleInfo()

    def visit(stmts: list) -> None:
        for st in stmts:
            if isinstance(st, ast.Import):
                for a in st.names:
                    info.imports[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
            elif isinstance(st, ast.ImportFrom):
                base = "." * st.level + (st.module or "")
                for a in st.names:
                    if a.name != "*":
                        info.imports[a.asname or a.name] = f"{base}.{a.name}" if st.module else f"{base}{a.name}"
            elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                info.defined.add(st.name)
            elif isinstance(st, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = st.targets if isinstance(st, ast.Assign) else [st.target]
                for t in targets:
                    info.defined.update(n.id for n in ast.walk(t) if isinstance(n, ast.Name))
            elif isinstance(st, (ast.If, ast.Try, ast.With)):     # guarded imports and definitions
                visit(st.body)
                visit(getattr(st, "orelse", []))
                for h in getattr(st, "handlers", []):
                    visit(h.body)
                visit(getattr(st, "finalbody", []))

    visit(tree.body)
    return info


def _self_name(fn: ast.AST | None) -> str | None:
    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = fn.args.posonlyargs + fn.args.args
        if args and not any(isinstance(d, ast.Name) and d.id == "staticmethod" for d in fn.decorator_list):
            return args[0].arg
    return None


def _read_before_bound(nodes: list, bound: set[str]) -> set[str]:
    """Names in `bound` that are nonetheless read before the code first
    binds them (`name = name.strip()` needs `name` from outside), by source
    position. Comprehension and lambda variables count as bound throughout:
    in `[u.name for u in users]` the read comes first in the source."""
    first_load: dict[str, tuple[int, int]] = {}
    first_store: dict[str, tuple[int, int]] = {}
    scoped: set[str] = set()
    # a target is bound once its value has been evaluated: in `x = x + 1`
    # the read comes first, though the target is written first
    bound_at: dict[int, tuple[int, int]] = {}
    for node in nodes:
        for n in ast.walk(node):
            pairs = []
            if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
                pairs = [(t, n.value) for t in (n.targets if isinstance(n, ast.Assign) else [n.target])]
            elif isinstance(n, ast.AugAssign):
                pairs = [(n.target, n.value)]
            elif isinstance(n, (ast.For, ast.AsyncFor)):
                pairs = [(n.target, n.iter)]
            elif isinstance(n, (ast.With, ast.AsyncWith)):
                pairs = [(i.optional_vars, i.context_expr) for i in n.items if i.optional_vars is not None]
            elif isinstance(n, ast.NamedExpr):
                pairs = [(n.target, n.value)]
            for target, value in pairs:
                end = (value.end_lineno or value.lineno, value.end_col_offset or 0)
                for x in ast.walk(target):
                    if isinstance(x, ast.Name):
                        bound_at[id(x)] = end
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n, ast.comprehension):
                scoped.update(x.id for x in ast.walk(n.target) if isinstance(x, ast.Name))
            elif isinstance(n, ast.Lambda):
                scoped.update(a.arg for a in n.args.posonlyargs + n.args.args + n.args.kwonlyargs)
            elif isinstance(n, ast.arg):
                first_store.setdefault(n.arg, (0, 0))       # parameters are bound from the start
            elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
                pos = (n.lineno, n.col_offset)
                first_load[n.target.id] = min(first_load.get(n.target.id, pos), pos)
            elif isinstance(n, ast.Name):
                pos = bound_at.get(id(n), (n.lineno, n.col_offset))
                table = first_load if isinstance(n.ctx, ast.Load) else first_store
                table[n.id] = min(table.get(n.id, pos), pos)
    return {name for name in bound - scoped
            if name in first_load and first_load[name] < first_store.get(name, (10**9, 0))}


def uses(nodes: list, bound: set[str], info: ModuleInfo, method: ast.AST | None) -> dict:
    """`nodes` are the function or the block's statements, `bound` the
    names they bind themselves, `method` the method whose `self` counts."""
    loaded: set[str] = set()
    self_attrs: set[str] = set()
    me = _self_name(method)
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                loaded.add(n.id)
            elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
                loaded.add(n.target.id)              # `y += 2` reads y first
            elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == me:
                self_attrs.add(n.attr)
    free = (loaded - bound - {me}) | _read_before_bound(nodes, bound & loaded)
    return {
        "imports": sorted({info.imports[n] for n in free if n in info.imports}),
        "globals": sorted(n for n in free if n in info.defined and n not in info.imports),
        "self_attrs": sorted(self_attrs),
        "outer": sorted(n for n in free if n not in info.imports and n not in info.defined and n not in _BUILTINS),
    }
