from __future__ import annotations

import random

import pytest

from sloptools.merge import index


def test_weights_favour_rare_statements():
    w = index.idf_weights([["a", "b"], ["a", "c"], ["a", "d"]])
    assert w["a"] == pytest.approx(1.0)          # in every sequence
    assert w["b"] > w["a"]


def test_lcs_is_weighted_and_order_aware():
    w = {"a": 1.0, "b": 1.0, "c": 5.0}
    weight, pairs = index.lcs(["a", "b", "c"], ["c", "a", "b"], w)
    assert weight == 5.0 and pairs == [(2, 0)]    # the heavy statement wins over two light ones
    assert index.similarity(["a", "b"], ["a", "b"], w) == 1.0
    assert index.similarity(["a", "b"], ["b", "a"], w) == pytest.approx(0.5)


@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("threshold", [0.5, 0.6, 0.8])
def test_candidates_never_miss_a_pair_above_the_threshold(seed, threshold):
    rnd = random.Random(seed)
    vocab = [f"s{i}" for i in range(12)]
    base = [rnd.choice(vocab) for _ in range(10)]
    seqs = []
    for _ in range(25):   # mutated copies of a common base, so many pairs are close
        s = list(base)
        for _ in range(rnd.randint(0, 6)):
            op = rnd.random()
            if op < 0.4 and s:
                s.pop(rnd.randrange(len(s)))
            elif op < 0.7:
                s.insert(rnd.randrange(len(s) + 1), rnd.choice(vocab))
            elif s:
                s[rnd.randrange(len(s))] = rnd.choice(vocab)
        seqs.append(s or ["s0"])
    w = index.idf_weights(seqs)
    found = set(index.candidate_pairs(seqs, w, threshold))
    for i in range(len(seqs)):
        for j in range(i + 1, len(seqs)):
            if index.similarity(seqs[i], seqs[j], w) >= threshold:
                assert (i, j) in found
