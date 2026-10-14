# sloptools

Deterministic code-quality tools for Python codebases. Everything is computed
from the source with plain AST analysis (no LLM), so the same code always
gives the same results.

| Tool | What it does |
|---|---|
| [`sloptrace`](#sloptrace) | Measures whether a codebase is getting messier, and tracks it over git history. |
| [`slopmerge`](#slopmerge) | Finds duplicated code, within and across codebases, that could be consolidated. |

## Install

```bash
pip install sloptools
```

Requires Python 3.9+.

## sloptrace

Is your Python codebase getting messier? sloptrace measures it, and tracks how
the numbers change over your git history.

It reports four things:

| Metric | What it tells you |
|---|---|
| **Erosion** | How much of your code's complexity is concentrated in a few huge functions, plus a ranked list of those functions. Watch the trend, not the absolute value. |
| **Clones** | Copy-pasted functions and code blocks, with `file:line` for each copy. |
| **Repeated literals** | Strings or lists of literals repeated across the code; usually a missing constant. |
| **Import cycles** | Modules that import each other and can't be understood on their own. |

The approach is adapted from the SlopCodeBench paper (Orlanski et al., 2025).

### Usage

```bash
sloptrace .                                  # analyse the current checkout
sloptrace /path/to/repo --history            # ...and how it changed over git history
sloptrace . --history --every 20 --max-commits 15   # sample every 20th commit, at most 15
sloptrace . --history --since 2024-01-01 -o out.json
sloptrace . --show-literals                  # also list repeated literals (noisy, off by default)
sloptrace --help                             # all options
```

Which files are scanned: in a git repo, everything tracked or untracked but
not ignored; otherwise the whole directory tree. Tests, docs, build output,
virtualenvs and vendored code are skipped by default; change that with
`--exclude`.

### Docs

[Metric reference](docs/metrics.html): the exact formula and a worked example
for each metric.

### Compared to scb-check

The paper's authors also publish [`scb-check`](https://pypi.org/project/scb-check/).
It supports many languages and flags code with lots of pattern rules.
sloptrace only handles Python, but gives you evidence (which functions, which
copies) and trends over history.

Its erosion number won't exactly match the paper's: the two tools count
branches slightly differently, so don't compare absolute values with the
paper's published baselines.

## slopmerge

Finds functions that have been copied, within one codebase or across
several, including copies that have drifted since, and blocks of statements
pasted into otherwise different functions. Each set of copies is reported
as a group: where every copy is, how similar it is, and what differs between
them. Groups are ordered by the lines a merge would save. It's built to feed a Claude skill that decides
what to consolidate, but the text summary works on its own too.

```bash
slopmerge .                                # duplication within one codebase
slopmerge ../api ../worker ../shared       # ...and between several (all treated as equals)
slopmerge ../api ../worker --cross-root-only   # only code shared between them
slopmerge . --min-similarity 0.8           # only close near-copies (default 0.6)
slopmerge . --units functions,classes      # leave out blocks and constants
slopmerge . --json                         # machine-readable output
slopmerge --help                           # all options
```

Each group has a tier:

| Tier | Meaning |
|---|---|
| **exact** | Identical apart from formatting, comments, docstrings, type annotations and decorators. |
| **renamed** | Identical apart from local names and literal values. The literals and outside names that differ are listed: they're what a merged function would take as arguments. |
| **near** | The same code with statements added, removed or changed, scored 0–1 against the group's most typical copy. Statements found all over the codebase count for little, so shared boilerplate alone doesn't make a match. The runs of statements that differ are located for each copy. |
| **related** | Written differently, but using the same calls, attributes, literals and exceptions in a similar amount of code: a loop and a comprehension computing the same thing, say. Low confidence, listed last, with the shared vocabulary as the reason. `--no-related` leaves them out. |

A group is of one kind of unit:

- **functions** (and methods);
- **blocks**: runs of statements copied into different functions
  (extract-a-helper candidates), as `exact` or `renamed` copies. A block's
  differing outside names are the parameters the helper would take;
- **constants**: the same literal list, tuple, set or dict in several places
  (column lists, choice tables, config maps). Dicts with the same keys and
  other values are `renamed`; near copies list the entries that differ;
- **classes**: classes declaring the same fields (dataclasses, models,
  records) or whose methods mostly match (a base class waiting to be
  extracted). Their matching methods are listed inside the class group.

Code that's duplicated on purpose or by a tool isn't reported: abstract
methods and stubs, one-line delegations, property accessors, `__init__`
methods that only store their arguments, attribute-list `__eq__`/`__repr__`/
`__hash__`, and generated files (protobuf, migrations, files headed "do not
edit"). Neither are functions made only of statements found all over the
codebase. What was left out is counted in the JSON output.

Each function or block copy also lists what it depends on (`uses`): the
imports, module globals and `self` attributes it reads, and for a block the
enclosing function's variables it needs, i.e. the parameters an extracted
helper would take.

See the [spec](docs/slopmerge-spec.md) for exactly how each kind of match works.

## Development

```bash
git clone https://github.com/sjtechdev/sloptools.git
cd sloptools
pip install -e ".[test]"
pytest
```
