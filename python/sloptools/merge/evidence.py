"""What differs between the members of a group, as evidence for the reader."""

from __future__ import annotations

from sloptools.merge import levels
from sloptools.merge.units import Function


def _json_value(v: object) -> object:
    return v if v is None or isinstance(v, (str, int, float, bool)) else repr(v)


def parameters(members: list[Function], ids: list[str]) -> list[dict]:
    """Positions where members of an equal-N1 group hold different literals
    or names, with each member's value.

    kind is "literal" for constants, "rename" for a name every member binds
    itself (a cosmetic rename, no parameter needed), and "reference" for a
    name that comes from outside the function in at least one member (it
    refers to different things, so a merged version would take it as an
    argument). Repeated occurrences of the same difference are reported
    once, with a count.
    """
    bound = [levels.bound_names(m.prepared) for m in members]
    found: dict[tuple, dict] = {}
    for column in zip(*(levels.leaves(m.prepared) for m in members)):
        if column[0] is None:
            continue
        values = tuple(leaf.value for leaf in column)
        if all(v == values[0] and type(v) is type(values[0]) for v in values):
            continue
        kind = column[0].kind
        if kind == "name":
            kind = "rename" if all(v in b for v, b in zip(values, bound)) else "reference"
        key = (kind, tuple(repr(v) for v in values))
        if key in found:
            found[key]["count"] += 1
            continue
        found[key] = {
            "kind": kind,
            "values": {i: _json_value(v) for i, v in zip(ids, values)},
            "lines": {i: leaf.line for i, leaf in zip(ids, column)},
            "count": 1,
        }
    return list(found.values())
