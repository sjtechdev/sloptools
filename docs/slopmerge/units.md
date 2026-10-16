# Units

Groups are made of one kind of unit.

| Unit | What it is |
|---|---|
| **function** | Every `def` / `async def`, including methods and nested ones. The docstring is ignored. |
| **block** | A run of statements copied into otherwise different functions (an "extract a helper" candidate). |
| **constant** | A literal list, tuple, set or dict of constants with at least 3 distinct entries. |
| **class** | A class compared on its declared fields and its methods. |

## Blocks

Blocks are matched by hash, so no `exact` or `renamed` block is missed.

1. Each statement list is cut at imports, `def`s and `class`es. Docstrings,
   `pass`, `...` and bare `return` are ignored.
2. Every position starts the shortest run holding at least
   `--min-statements` statements (nested ones count).
3. Runs with the same renamed form (see [matching](matching.md)) in two or
   more non-overlapping places are a candidate group.
4. The group grows statement by statement, both ways, while all copies agree.

A block group is dropped if it is only plain stores or import guards, only
module/class-level assignments, back-to-back repetition in one list, made
of common statements only, inside a boilerplate function, or entirely
inside copies of a function group already reported.

Names a block reads but doesn't define show up as `reference` parameters:
what an extracted helper would take. Drifted copies of blocks (`near`
blocks) aren't matched; a drifted copy that dominates its function is still
found as a `near` function.

## Constants

Any all-constant literal with 3+ distinct entries counts, wherever it
appears (module, class, default argument, inside a function). `__all__` and
`__slots__` are skipped. A constant assigned to a name is called by that
name.

- `exact`: same value. Lists and tuples compare in order; sets and dicts
  don't.
- `renamed`: dicts with the same keys and different values. Each differing
  value is a parameter.
- `near`: scored on entries (a dict's keys) with rare entries weighing more
  than `"id"` or `"name"`. Needs at least 3 shared entries. Differences list
  the entries each copy adds or lacks.

A list and a set with the same entries end up in one group at 1.0.
Constants inside a reported function or block group are left to that group.

## Classes

A class becomes a set of tokens: one per declared field and one per method
that belongs to a function group. A method matching nothing gets its own
token, which counts against the match. Classes are scored by weighted
overlap and need 3 shared tokens, or 2 matching methods. One score covers
both "same fields" (dataclasses, models) and "same methods" (a base class
waiting to be extracted), so a class matching both is reported once.

**Fields** are annotated class attributes (not `ClassVar`), class attributes
assigned a call (`email = models.CharField(...)`), and `self.x` assigned in
`__init__`. Literal class attributes (`name = "MIPS"`) are configuration,
not fields.

`exact` and `renamed` classes have the same fields and matching methods;
`exact` also needs identical field types and verbatim methods. Differing
field types are parameters. `near` classes list the fields and methods each
copy adds or lacks.

A function group made only of methods from one class group is listed inside
that group as a child (ids like `g3.1`).
