# Internals

## Layout

slopmerge lives in the `sloptools` package next to sloptrace and shares its
version. Shared code is in `sloptools.common` (file discovery, the AST
normaliser, SLOC); the two tools don't import each other. `sloptools.merge`
uses only the standard library.

```
python/sloptools/
  common/    discover.py, normalise.py, sloc.py
  trace/     sloptrace
  merge/     slopmerge
    cli.py        units.py      levels.py     index.py
    match.py      evidence.py   report.py     tests/
```

## Performance

Target: 200k SLOC in under 30 seconds, single process (131k lines takes
about 7 seconds today). Files aren't parsed in parallel.

Scoring every pair would be quadratic, so `near` candidates come from an
inverted index using **prefix filtering**, which provably misses nothing at
or above the threshold: if `sim(a, b) ≥ t`, the weight they share is at
least `t · W(a) / (2 − t)`. Statements are ordered rarest first, and each
unit is indexed under the shortest prefix that must overlap. Two cheap
bounds (relative size, statement-bag overlap) then discard most candidates
before any LCS runs. A randomised test checks the no-miss property against
brute force.

## Tests

- Unit tests per module.
- A labelled corpus in `tests/corpus/` (roots `app` and `lib`) with
  expectations in `tests/test_corpus.py`. Every function in it is either in
  an expected group or a negative that must not match (property
  boilerplate, `__init__` stores, delegations, same-shape-different-ops,
  generated `_pb2` code, and so on).
- The corpus test requires no missed `exact`/`renamed` matches, no grouped
  negatives, and `near` recall and overall precision of at least 0.85.
- Output is deterministic: two runs give identical JSON.
- Before a release, run on a few real codebases and review the top 20
  groups by hand.

## Possible follow-ups

- Near blocks (drifted copies of copied runs).
- Cap `differences` for very large near constants.
