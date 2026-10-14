from __future__ import annotations

import ast
import textwrap

from sloptools.merge import levels
from sloptools.merge.uses import module_info, uses

MODULE = """
import os.path
import numpy as np
from sqlalchemy import text as sql
from . import helpers
LIMIT = 10

def top_level():
    pass
"""


def _uses_of_function(src: str) -> dict:
    tree = ast.parse(textwrap.dedent(MODULE + src))
    fn = tree.body[-1]
    return uses([fn], levels.bound_names([fn], fn), module_info(tree), None)


def _uses_of_block(src: str, first: int, last: int) -> dict:
    """The statements first..last (0-based, inclusive) of the last function's body."""
    tree = ast.parse(textwrap.dedent(MODULE + src))
    fn = tree.body[-1]
    stmts = fn.body[first:last + 1]
    method = fn if fn.args.args and fn.args.args[0].arg == "self" else None
    return uses(stmts, levels.bound_names(stmts), module_info(tree), method)


def test_imports_resolve_to_what_they_refer_to():
    u = _uses_of_function("""
def f(q):
    rows = np.array(sql(q))
    return os.path.join(helpers.ROOT, str(rows)), LIMIT, top_level(), len(rows)
""")
    assert u["imports"] == [".helpers", "numpy", "os", "sqlalchemy.text"]
    assert u["globals"] == ["LIMIT", "top_level"]
    assert u["outer"] == []           # parameters and locals are its own; builtins are left out


def test_a_blocks_outer_names_are_the_helpers_parameters():
    u = _uses_of_block("""
def g(name, owner, limit):
    if not name:
        raise ValueError("name")
    name = name.strip()
    total = 0
    total = total + limit
    for item in owner.items:
        total += item.size
    return name, total
""", 0, 5)
    # name is read before it's rebound; limit and owner come from g; total is the block's own
    assert u["outer"] == ["limit", "name", "owner"]


def test_reading_a_name_in_its_own_assignment_counts_as_outside():
    u = _uses_of_block("""
def g(x, y):
    x = x + 1
    y += 2
    z = [w * 2 for w in range(x)]
    return z
""", 0, 2)
    assert u["outer"] == ["x", "y"]    # w is the comprehension's own


def test_self_attributes_of_the_method():
    u = _uses_of_block("""
def run(self, key):
    value = self.cache.get(key)
    self.hits += 1
    return value
""", 0, 1)
    assert u["self_attrs"] == ["cache", "hits"] and u["outer"] == ["key"]
