# sloptools

Code-quality tools for Python. Everything is plain AST analysis (no LLM), so
the same code always gives the same results.

| Tool | What it does |
|---|---|
| [`sloptrace`](#sloptrace) | Measures whether a codebase is getting messier, and tracks it over git history. |
| [`slopmerge`](#slopmerge) | Finds duplicated code, within and across codebases, that could be merged. |

## Install

```bash
pip install sloptools
```

Requires Python 3.9+.

## sloptrace

```bash
sloptrace .                          # analyse the current checkout
sloptrace . --history                # ...and how it changed over git history
sloptrace . --history --every 20 --max-commits 15
sloptrace . --show-literals          # also list repeated literals (noisy)
sloptrace --help
```

It reports four things:

| Metric | What it tells you |
|---|---|
| **Erosion** | How much complexity sits in a few huge functions, with a ranked list. Watch the trend, not the number. |
| **Clones** | Copy-pasted functions and blocks, with `file:line` for each. |
| **Repeated literals** | Strings or lists repeated across the code; usually a missing constant. |
| **Import cycles** | Modules that import each other. |

Files scanned: in a git repo, everything tracked or untracked but not
ignored; otherwise the whole tree. Tests, docs, build output, virtualenvs and
vendored code are skipped; change that with `--exclude`.

Formulas and a worked example for each metric: [docs/metrics.html](docs/metrics.html).

Based on the SlopCodeBench paper (Orlanski et al., 2025). Its authors also
publish [`scb-check`](https://pypi.org/project/scb-check/), which covers many
languages. sloptrace is Python-only but shows which functions and copies are
the problem, and how things trend. Its erosion number counts branches
slightly differently, so don't compare it to the paper's baselines.

## slopmerge

```bash
slopmerge .                              # duplication within one codebase
slopmerge ../api ../worker               # ...and between several
slopmerge ../api ../worker --cross-root-only
slopmerge . --min-similarity 0.8         # only close near-copies
slopmerge . --json                       # machine-readable
slopmerge --help
```

It reports groups of copies, biggest saving first, with where each copy is,
how similar it is, and what differs. Four tiers, from most to least certain:

- **exact**: identical apart from formatting and comments.
- **renamed**: identical apart from local names and literal values.
- **near**: statements added, removed or changed.
- **related**: written differently but using the same calls and literals.

It finds copied functions, pasted blocks, repeated constant tables, and
classes with the same fields or methods. Boilerplate (stubs, accessors,
generated files) is left out.

Details: [docs/slopmerge/](docs/slopmerge/README.md).

## Development

```bash
git clone https://github.com/sjtechdev/sloptools.git
cd sloptools
pip install -e ".[test]"
pytest
```
