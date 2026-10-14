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

from sloptools.merge import blocks, classes, constants, index, levels, related
from sloptools.merge.units import Scan, Unit

TIERS = ("exact", "renamed", "near", "related")


@dataclass
class Group:
    tier: str
    members: list[Unit]     # sorted by location; all of one kind (function, block, constant, class)
    variants: list[int]         # per member: 1-based index of its N0 form
    shapes: list[int]           # per member: 1-based index of its N1 form
    medoid: int                 # index into members
    similarity: list[float]     # per member, to the medoid
    # per member: matched (member element, medoid element) index pairs
    alignment: list[list[tuple[int, int]]] = field(repr=False)
    children: list["Group"] = field(default_factory=list)   # method groups inside a class group
    # class groups only, per member: its profile, and its method tokens -> method names
    profiles: list[list[str]] | None = field(default=None, repr=False)
    method_names: list[dict[str, list[str]]] | None = field(default=None, repr=False)

    @property
    def unit(self) -> str:
        return self.members[0].kind

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


def _contains(outer: Unit, inner: Unit) -> bool:
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


def _distinctive_test(shapes: list[list[Unit]]):
    """A test for "has at least one statement that isn't common", with
    statement frequencies taken from the function shapes. Code made only of
    statements found all over the codebase (`x = None`, `return x`,
    `for x in y`) has nothing to recognise it by, however long it is."""
    df = Counter(k for ms in shapes for k in {e.key for e in ms[0].seq[1:] if e.node is not None})
    cap = max(COMMON_MIN_SHAPES, COMMON_FRACTION * len(shapes))

    def distinctive(elems: list[levels.Elem]) -> bool:
        return any(e.node is not None and df[e.key] <= cap for e in elems)
    return distinctive


def find_groups(scan: Scan, root_order: dict[str, int], min_statements: int, min_similarity: float,
                units: tuple[str, ...] = ("functions", "blocks", "constants", "classes"),
                with_related: bool = True) -> tuple[list[Group], int]:
    """Duplicate groups, biggest estimated savings first, then by tier and
    location, with `related` groups (speculative) last; and the number of
    groups dropped as subsumed."""
    def where(f: Unit):
        return (root_order[f.root], f.rel, f.lo, f.qualname)

    by_n1: dict[str, list[Unit]] = defaultdict(list)
    for f in scan.functions:
        if f.statements >= min_statements:
            by_n1[f.n1].append(f)
    shapes = sorted((sorted(ms, key=where) for ms in by_n1.values()), key=lambda ms: where(ms[0]))
    distinctive = _distinctive_test(shapes)
    shapes = [ms for ms in shapes if distinctive(ms[0].seq[1:])]
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

    function_groups = _cluster(shapes, keys, w, min_similarity, score, nested, where)
    groups: list[Group] = list(function_groups) if "functions" in units else []
    if with_related and "functions" in units:
        groups += _related_groups(shapes, function_groups, min_similarity, nested, where)
    if "classes" in units:
        eligible = [f for ms in shapes for f in ms]
        class_groups = _class_groups(scan.classes, eligible, function_groups, min_similarity, where)
        groups += class_groups
        groups = _nest_method_groups(groups, class_groups)
    if "blocks" in units:
        groups.extend(_block_group(copies, where) for copies in blocks.find(scan.bodies, min_statements, distinctive))
    if "constants" in units:
        groups += _constant_groups(scan.constants, min_similarity, where)

    kept_groups = [g for g in groups if not _subsumed(g, groups)]
    kept_groups.sort(key=lambda g: (g.tier == "related", -g.savings, TIERS.index(g.tier), where(g.members[0])))
    return kept_groups, len(groups) - len(kept_groups)


def _cluster(shapes: list[list[Unit]], keys: list[list[str]], w: dict[str, float], threshold: float,
             score, nested, where) -> list[Group]:
    """Groups from shapes: one per shape with two or more members and no
    near neighbours, and `near` groups of shapes scoring at least
    `threshold`, split at the medoid against chaining. `score(a, b)` gives
    shape a's similarity to b and its alignment onto b; `nested(a, b)` says
    two shapes must never share a group."""
    edges: dict[tuple[int, int], float] = {}
    for a, b in index.candidate_pairs(keys, w, threshold):
        if nested(a, b):
            continue
        sim = score(a, b)[0]
        if sim >= threshold:
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
            if score(s, medoid)[0] >= threshold and not any(nested(s, k) for k in kept):
                kept.append(s)
        kept.sort()
        rest = [s for s in comp if s not in kept]
        groups.append(_group(shapes, kept, medoid, score, where))
        if rest:
            work.extend(_components(rest, edges))
    return groups


def _group(shapes: list[list[Unit]], comp: list[int], medoid_shape: int, score, where) -> Group:
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


def _block_group(copies: list[Unit], where) -> Group:
    members = sorted(copies, key=where)
    n0_order = list(dict.fromkeys(u.n0 for u in members))
    variants = [n0_order.index(u.n0) + 1 for u in members]
    common = Counter(variants).most_common(1)[0][0]
    return Group(tier="exact" if len(n0_order) == 1 else "renamed", members=members, variants=variants,
                 shapes=[1] * len(members), medoid=variants.index(common), similarity=[1.0] * len(members),
                 alignment=[[(i, i) for i in range(len(u.seq))] for u in members])


def _constant_groups(units: list[Unit], threshold: float, where) -> list[Group]:
    """Constant tables, grouped like functions: equal structure (N1) is one
    shape, and shapes are joined into near groups by their weighted overlap."""
    by_n1: dict[str, list[Unit]] = defaultdict(list)
    for u in units:
        by_n1[u.n1].append(u)
    shapes = sorted((sorted(us, key=where) for us in by_n1.values()), key=lambda us: where(us[0]))
    keys = [constants.elements(us[0].nodes[0]) for us in shapes]
    w = index.idf_weights(keys)
    cache: dict[tuple[int, int], float] = {}

    def score(a: int, b: int) -> tuple[float, list]:
        if (a, b) not in cache:
            cache[(a, b)] = constants.score(shapes[a][0], shapes[b][0], w)
        return cache[(a, b)], []

    return _cluster(shapes, keys, w, threshold, score, lambda a, b: False, where)


def _owner(m: Unit) -> tuple[str, str, str] | None:
    """The class a method belongs to, as (root, file, class qualname)."""
    return (m.root, m.rel, m.qualname.rsplit(".", 1)[0]) if m.kind == "function" and m.is_method else None


def _class_groups(class_units: list[Unit], methods: list[Unit], function_groups: list[Group],
                  threshold: float, where) -> list[Group]:
    """Classes grouped by their profiles: fields and matching methods."""
    group_of = {id(m): gi for gi, g in enumerate(function_groups) for m in g.members}
    by_class: dict[tuple, list[Unit]] = defaultdict(list)
    for m in methods:
        if (o := _owner(m)) is not None:
            by_class[o].append(m)
    profiles: dict[int, list[str]] = {}
    names: dict[int, dict[str, list[str]]] = {}
    for c in class_units:
        ms = sorted(by_class.get((c.root, c.rel, c.qualname), []), key=where)
        tokens = classes.set_forms(c, ms, group_of)
        if classes.enough(tokens):
            profiles[id(c)] = tokens
            names[id(c)] = defaultdict(list)
            for m in ms:
                names[id(c)][classes.method_token(m, group_of)].append(m.qualname.rsplit(".", 1)[1])

    by_n1: dict[str, list[Unit]] = defaultdict(list)
    for c in class_units:
        if id(c) in profiles:
            by_n1[c.n1].append(c)
    shapes = sorted((sorted(cs, key=where) for cs in by_n1.values()), key=lambda cs: where(cs[0]))
    keys = [profiles[id(cs[0])] for cs in shapes]
    w = index.idf_weights(keys)
    cache: dict[tuple[int, int], float] = {}

    def score(a: int, b: int) -> tuple[float, list]:
        if (a, b) not in cache:
            cache[(a, b)] = classes.score(keys[a], keys[b], w)
        return cache[(a, b)], []

    def nested(a: int, b: int) -> bool:
        return any(_contains(x, y) or _contains(y, x) for x in shapes[a] for y in shapes[b])

    out = _cluster(shapes, keys, w, threshold, score, nested, where)
    for g in out:
        g.profiles = [profiles[id(c)] for c in g.members]
        g.method_names = [dict(names[id(c)]) for c in g.members]
    return out


def _nest_method_groups(groups: list[Group], class_groups: list[Group]) -> list[Group]:
    """A function group made only of methods of one class group's members
    is listed inside it, as a child, instead of on its own."""
    members_of = [{(c.root, c.rel, c.qualname) for c in cg.members} for cg in class_groups]
    out = []
    for g in groups:
        owners = {_owner(m) for m in g.members} if g.unit == "function" else {None}
        home = next((cg for cg, ms in zip(class_groups, members_of) if None not in owners and owners <= ms), None)
        if home is None:
            out.append(g)
        else:
            home.children.append(g)
    return out


def _related_groups(shapes: list[list[Unit]], function_groups: list[Group], threshold: float,
                    nested_shapes, where) -> list[Group]:
    """Functions that matched nothing structurally, grouped by vocabulary."""
    grouped = {id(m) for g in function_groups for m in g.members}
    lone = [i for i, ms in enumerate(shapes) if len(ms) == 1 and id(ms[0]) not in grouped]
    vocab = [related.vocabulary(ms[0]) for ms in shapes]
    w = index.idf_weights(vocab)           # frequencies over all functions, not only the lone ones
    sub = [shapes[i] for i in lone]
    keys = [vocab[i] for i in lone]
    cache: dict[tuple[int, int], float] = {}

    def score(a: int, b: int) -> tuple[float, list]:
        if (a, b) not in cache:
            cache[(a, b)] = related.score(keys[a], keys[b], sub[a][0].statements, sub[b][0].statements, w)
        return cache[(a, b)], []

    out = _cluster(sub, keys, w, threshold, score, lambda a, b: nested_shapes(lone[a], lone[b]), where)
    for g in out:
        g.tier = "related"
    return out
