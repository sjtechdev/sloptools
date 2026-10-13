"""Grouping functions into duplicate groups, by tier.

Milestone 1 has the two hash-based tiers: `exact` (equal N0) and `renamed`
(equal N1, not all N0 equal). Both are found by bucketing, so no such copy
can be missed.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from sloptools.merge.units import Function

TIERS = ("exact", "renamed")


@dataclass
class Group:
    tier: str
    members: list[Function]     # sorted by location
    variants: list[int]         # per member: 1-based index of its N0 form
    medoid: int                 # index into members

    @property
    def roots(self) -> list[str]:
        return sorted({m.root for m in self.members})

    @property
    def savings(self) -> int:
        """Lines removed by keeping one copy: total SLOC minus the largest."""
        sizes = [m.sloc for m in self.members]
        return sum(sizes) - max(sizes)


def _contains(outer: Function, inner: Function) -> bool:
    return (outer.root, outer.rel) == (inner.root, inner.rel) and outer.lo <= inner.lo \
        and inner.hi <= outer.hi and outer.span != inner.span


def _subsumed(g: Group, others: list[Group]) -> bool:
    """Every member sits inside a member of one other group: a nested
    function copied along with the function around it."""
    return any(h is not g and all(any(_contains(o, m) for o in h.members) for m in g.members)
               for h in others)


def find_groups(functions: list[Function], root_order: dict[str, int], min_statements: int) -> tuple[list[Group], int]:
    """Duplicate groups, ordered by tier, then savings, then location; and
    the number of groups dropped as subsumed."""
    def where(f: Function):
        return (root_order[f.root], f.rel, f.lo, f.qualname)

    buckets: dict[str, list[Function]] = defaultdict(list)
    for f in functions:
        if f.statements >= min_statements:
            buckets[f.n1].append(f)

    groups = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        members.sort(key=where)
        order = list(dict.fromkeys(m.n0 for m in members))
        variants = [order.index(m.n0) + 1 for m in members]
        common = Counter(variants).most_common(1)[0][0]   # ties go to the first variant seen
        groups.append(Group(tier="exact" if len(order) == 1 else "renamed", members=members,
                            variants=variants, medoid=variants.index(common)))

    kept = [g for g in groups if not _subsumed(g, groups)]
    kept.sort(key=lambda g: (TIERS.index(g.tier), -g.savings, where(g.members[0])))
    return kept, len(groups) - len(kept)

