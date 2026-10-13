"""What differs between the members of a group, as evidence for the reader.

Both functions work from each member's alignment onto the medoid: which of
the member's statements match which of the medoid's.
"""

from __future__ import annotations

from sloptools.merge import levels
from sloptools.merge.units import Function


def _json_value(v: object) -> object:
    return v if v is None or isinstance(v, (str, int, float, bool)) else repr(v)


def parameters(members: list[Function], ids: list[str], medoid: int,
               alignment: list[list[tuple[int, int]]]) -> list[dict]:
    """Positions in matched statements where members hold different
    literals or names, with each member's value.

    kind is "literal" for constants, "rename" for a name every member binds
    itself (a cosmetic rename, no parameter needed), and "reference" for a
    name that comes from outside the function in at least one member (it
    refers to different things, so a merged version would take it as an
    argument). A member whose copy of the statement is missing (a near
    copy) is left out of that entry. Repeated occurrences of the same
    difference are reported once, with a count.
    """
    bound = [levels.bound_names(m.node) for m in members]
    onto_medoid = [{j: i for i, j in pairs} for pairs in alignment]
    found: dict[tuple, dict] = {}
    for j, elem in enumerate(members[medoid].seq):
        present = [(k, m.seq[onto_medoid[k][j]]) for k, m in enumerate(members) if j in onto_medoid[k]]
        if len(present) < 2:
            continue
        columns = zip(*(levels.leaves(e) for _, e in present))
        for column in columns:
            values = tuple(leaf.value for leaf in column)
            if all(v == values[0] and type(v) is type(values[0]) for v in values):
                continue
            kind = column[0].kind
            if kind == "name":
                kind = "rename" if all(v in bound[k] for v, (k, _) in zip(values, present)) else "reference"
            key = (kind, tuple((k, repr(v)) for v, (k, _) in zip(values, present)))
            if key in found:
                found[key]["count"] += 1
                continue
            found[key] = {
                "kind": kind,
                "values": {ids[k]: _json_value(v) for v, (k, _) in zip(values, present)},
                "lines": {ids[k]: leaf.line for leaf, (k, _) in zip(column, present)},
                "count": 1,
            }
    return list(found.values())


def _span(elems: list[levels.Elem]) -> list[int]:
    return [min(e.lo for e in elems), max(e.hi for e in elems)]


def differences(members: list[Function], ids: list[str], medoid: int,
                alignment: list[list[tuple[int, int]]]) -> list[dict]:
    """For each member that isn't a renamed copy of the medoid, the runs of
    statements between matched ones: "added" (only in the member), "removed"
    (only in the medoid), or "changed" (both, in the same place)."""
    out = []
    med = members[medoid].seq
    for k, m in enumerate(members):
        pairs = alignment[k]
        if len(pairs) == len(m.seq) == len(med):
            continue
        anchors = [(-1, -1)] + pairs + [(len(m.seq), len(med))]
        for (i0, j0), (i1, j1) in zip(anchors, anchors[1:]):
            mine, theirs = m.seq[i0 + 1:i1], med[j0 + 1:j1]
            if not mine and not theirs:
                continue
            entry = {"member": ids[k],
                     "change": "changed" if mine and theirs else "added" if mine else "removed"}
            if mine:
                entry["lines"] = _span(mine)
            if theirs:
                entry["medoid_lines"] = _span(theirs)
            out.append(entry)
    return out
