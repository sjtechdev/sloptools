"""Statement weights, candidate pairs, and the similarity score.

A function's N1 statement sequence is scored against another's as

    sim(a, b) = 2 * W(LCS(a, b)) / (W(a) + W(b))

where W sums statement weights. A statement's weight is its smoothed IDF,
ln((1 + N) / (1 + df)) + 1, over the N units being compared: a statement
found in most functions weighs about 1, one found in two weighs ln(N/3) + 1.
(Plain log(N/df) would make a statement shared by every unit weigh 0, which
breaks small codebases: with two functions, everything they share is
"everywhere".)

Candidates come from prefix filtering, so no pair scoring at or above the
threshold is missed: if sim(a, b) >= t, the weight the two share is at least
t * W(a) / (2 - t) (because it can't exceed W(b)). Order every statement
occurrence rarest first; then a's shortest prefix whose remaining weight is
below that bound must share an occurrence with b's prefix. Units are
indexed under their prefix only, and only units sharing an index key are
scored.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Sequence


def idf_weights(sequences: Sequence[Sequence[str]]) -> dict[str, float]:
    n = len(sequences)
    df = Counter(k for seq in sequences for k in set(seq))
    return {k: math.log((1 + n) / (1 + d)) + 1 for k, d in df.items()}


def total(seq: Sequence[str], w: dict[str, float]) -> float:
    return sum(w[k] for k in seq)


def lcs(a: Sequence[str], b: Sequence[str], w: dict[str, float]) -> tuple[float, list[tuple[int, int]]]:
    """Weighted longest common subsequence: its weight, and the matched
    (index in a, index in b) pairs in order."""
    n, m = len(a), len(b)
    prev = [0.0] * (m + 1)
    rows = [prev]
    for i in range(1, n + 1):
        cur = [0.0] * (m + 1)
        ai, wi = a[i - 1], w[a[i - 1]]
        for j in range(1, m + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + wi
            else:
                cur[j] = cur[j - 1] if cur[j - 1] > prev[j] else prev[j]
        rows.append(cur)
        prev = cur
    pairs = []
    i, j = n, m
    while i and j:
        if a[i - 1] == b[j - 1] and rows[i][j] == rows[i - 1][j - 1] + w[a[i - 1]]:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif rows[i - 1][j] >= rows[i][j - 1]:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return rows[n][m], pairs


def similarity(a: Sequence[str], b: Sequence[str], w: dict[str, float]) -> float:
    denom = total(a, w) + total(b, w)
    return 2 * lcs(a, b, w)[0] / denom if denom else 0.0


def _occurrences(seq: Sequence[str]) -> list[tuple[str, int]]:
    """Each statement tagged with how many times it has appeared before, so
    repeats are distinct items (LCS counts multiplicity)."""
    seen: Counter = Counter()
    out = []
    for k in seq:
        out.append((k, seen[k]))
        seen[k] += 1
    return out


def candidate_pairs(sequences: Sequence[Sequence[str]], w: dict[str, float], threshold: float) -> list[tuple[int, int]]:
    """Index pairs (i < j) that could score >= threshold, after the cheap
    bounds: sizes too far apart, or too little shared weight, rule a pair out
    before any LCS is computed."""
    weights = [total(s, w) for s in sequences]
    bags = [Counter(s) for s in sequences]
    index: dict[tuple[str, int], list[int]] = defaultdict(list)
    for i, seq in enumerate(sequences):
        items = sorted(_occurrences(seq), key=lambda o: (-w[o[0]], o))
        need = threshold * weights[i] / (2 - threshold)
        rest = weights[i]
        for item in items:
            if rest < need:
                break
            index[item].append(i)
            rest -= w[item[0]]

    seen: set[tuple[int, int]] = set()
    for posting in index.values():
        for x in range(len(posting)):
            for y in range(x + 1, len(posting)):
                seen.add((posting[x], posting[y]))

    out = []
    for i, j in sorted(seen):
        wi, wj = weights[i], weights[j]
        if 2 * min(wi, wj) < threshold * (wi + wj):
            continue
        shared = sum(w[k] * min(c, bags[j][k]) for k, c in bags[i].items() if k in bags[j])
        if 2 * shared >= threshold * (wi + wj):
            out.append((i, j))
    return out
