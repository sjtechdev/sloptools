"""Grouping functions into duplicate groups, by tier.

Functions with equal N1 forms (a "shape") are certain copies of each other:
`exact` if their N0 forms are equal too, `renamed` otherwise. Shapes are then
scored against each other (see index.py), and shapes scoring at least the
threshold are joined into `near` groups; a near group takes in every member
of its shapes, so an exact or renamed group inside it isn't reported
separately.

Chaining is guarded against: A~B and B~C don't make a group if A and C are
unrelated. Within a connected component, every shape must score at least
the threshold against the component's medoid (the shape with the highest
total similarity to the other functions); the rest are split off and grouped
again.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sloptools.merge import index
from sloptools.merge.units import Function

TIERS = ("exact", "renamed", "near")


@dataclass
class Group:
    tier: str
    members: list[Function]     # sorted by location
    variants: list[int]         # per member: 1-based index of its N0 form
    shapes: list[int]           # per member: 1-based index of its N1 form
    medoid: int                 # index into members
    similarity: list[float]     # per member, to the medoid
    # per member: matched (member element, medoid element) index pairs
    alignment: list[list[tuple[int, int]]] = field(repr=False)

    @property
    def roots(self) -> list[str]:
        return sorted({m.root for m in self.members})

    @property
    def savings(self) -> int:
        """Lines removed by keeping one copy: total SLOC minus the largest."""
        sizes = [m.sloc for m in self.members]
        return sum(sizes) - max(sizes)

    @property
    def similarity_range(self) -> tuple[float, float]:
        others = [s for i, s in enumerate(self.similarity) if i != self.medoid] or [1.0]
        return min(others), max(others)


def _contains(outer: Function, inner: Function) -> bool:
    return (outer.root, outer.rel) == (inner.root, inner.rel) and outer.lo <= inner.lo \
        and inner.hi <= outer.hi and outer.span != inner.span


def _subsumed(g: Group, others: list[Group]) -> bool:
    """Every member sits inside a member of one other group: a nested
    function copied along with the function around it."""
    return any(h is not g and all(any(_contains(o, m) for o in h.members) for m in g.members)
               for h in others)


class _Components:
    """Union-find over shape indices."""

    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _components(nodes: list[int], edges: dict[tuple[int, int], float]) -> list[list[int]]:
    uf = _Components(max(nodes) + 1)
    node_set = set(nodes)
    for a, b in edges:
        if a in node_set and b in node_set:
            uf.union(a, b)
    by_root: dict[int, list[int]] = defaultdict(list)
    for n in sorted(nodes):
        by_root[uf.find(n)].append(n)
    return list(by_root.values())


COMMON_MIN_SHAPES = 20      # a statement in more shapes than this (or 2% of them) is common
COMMON_FRACTION = 0.02


def _distinctive(shapes: list[list[Function]]) -> list[list[Function]]:
    """Shapes with at least one statement that isn't common. A function made
    only of statements found all over the codebase (`x = None`, `return x`,
    `for x in y`) has nothing to recognise it by, however long it is."""
    df = Counter(k for ms in shapes for k in {e.key for e in ms[0].seq[1:] if e.node is not None})
    cap = max(COMMON_MIN_SHAPES, COMMON_FRACTION * len(shapes))
    return [ms for ms in shapes if any(e.node is not None and df[e.key] <= cap for e in ms[0].seq[1:])]


def find_groups(functions: list[Function], root_order: dict[str, int], min_statements: int,
                min_similarity: float) -> tuple[list[Group], int]:
    """Duplicate groups, ordered by tier, then savings, then location; and
    the number of groups dropped as subsumed."""
    def where(f: Function):
        return (root_order[f.root], f.rel, f.lo, f.qualname)

    by_n1: dict[str, list[Function]] = defaultdict(list)
    for f in functions:
        if f.statements >= min_statements:
            by_n1[f.n1].append(f)
    shapes = sorted((sorted(ms, key=where) for ms in by_n1.values()), key=lambda ms: where(ms[0]))
    shapes = _distinctive(shapes)
    keys = [[e.key for e in ms[0].seq] for ms in shapes]
    w = index.idf_weights(keys)

    aligned: dict[tuple[int, int], tuple[float, list[tuple[int, int]]]] = {}

    def score(a: int, b: int) -> tuple[float, list[tuple[int, int]]]:
        """Similarity of shape a to shape b, and the alignment of a onto b."""
        if (a, b) not in aligned:
            weight, pairs = index.lcs(keys[a], keys[b], w)
            denom = index.total(keys[a], w) + index.total(keys[b], w)
            aligned[(a, b)] = (2 * weight / denom if denom else 0.0, pairs)
        return aligned[(a, b)]

    def nested(a: int, b: int) -> bool:
        """A function and one nested inside it share statements by
        construction; they aren't copies of each other."""
        return any(_contains(x, y) or _contains(y, x) for x in shapes[a] for y in shapes[b])

    edges: dict[tuple[int, int], float] = {}
    for a, b in index.candidate_pairs(keys, w, min_similarity):
        if nested(a, b):
            continue
        sim = score(a, b)[0]
        if sim >= min_similarity:
            edges[(a, b)] = edges[(b, a)] = sim

    groups: list[Group] = []
    work = _components(list(range(len(shapes))), edges) if shapes else []
    while work:
        comp = work.pop(0)
        if len(comp) == 1:
            if len(shapes[comp[0]]) >= 2:
                groups.append(_group(shapes, comp, comp[0], score, where))
            continue
        size = {s: len(shapes[s]) for s in comp}
        total_sim = {s: (size[s] - 1) + sum(edges.get((s, o), 0.0) * size[o] for o in comp if o != s)
                     for s in comp}
        medoid = max(comp, key=lambda s: (total_sim[s], -s))
        # closest to the medoid first; never two members where one is nested in the other
        kept = [medoid]
        for s in sorted((s for s in comp if s != medoid), key=lambda s: (-score(s, medoid)[0], s)):
            if score(s, medoid)[0] >= min_similarity and not any(nested(s, k) for k in kept):
                kept.append(s)
        kept.sort()
        rest = [s for s in comp if s not in kept]
        groups.append(_group(shapes, kept, medoid, score, where))
        if rest:
            work.extend(_components(rest, edges))

    kept_groups = [g for g in groups if not _subsumed(g, groups)]
    kept_groups.sort(key=lambda g: (TIERS.index(g.tier), -g.savings, where(g.members[0])))
    return kept_groups, len(groups) - len(kept_groups)


def _group(shapes: list[list[Function]], comp: list[int], medoid_shape: int, score, where) -> Group:
    pick = sorted(((f, s) for s in comp for f in shapes[s]), key=lambda fs: where(fs[0]))
    members = [f for f, _ in pick]
    member_shapes = [s for _, s in pick]
    n0_order = list(dict.fromkeys(f.n0 for f in members))
    variants = [n0_order.index(f.n0) + 1 for f in members]
    shape_order = list(dict.fromkeys(member_shapes))
    in_medoid = [i for i, s in enumerate(member_shapes) if s == medoid_shape]
    common = Counter(variants[i] for i in in_medoid).most_common(1)[0][0]
    medoid = next(i for i in in_medoid if variants[i] == common)

    similarity, alignment = [], []
    for f, s in pick:
        if s == medoid_shape:
            similarity.append(1.0)
            alignment.append([(i, i) for i in range(len(f.seq))])
        else:
            sim, pairs = score(s, medoid_shape)
            similarity.append(round(sim, 3))
            alignment.append(pairs)
    if len(shape_order) > 1:
        tier = "near"
    else:
        tier = "exact" if len(n0_order) == 1 else "renamed"
    return Group(tier=tier, members=members, variants=variants,
                 shapes=[shape_order.index(s) + 1 for s in member_shapes], medoid=medoid,
                 similarity=similarity, alignment=alignment)
