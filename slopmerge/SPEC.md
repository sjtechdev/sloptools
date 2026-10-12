# slopmerge: spec

> Working name. Status: draft, nothing implemented yet.

slopmerge finds Python code that has been duplicated, either copied or
reimplemented, across one or more codebases, and reports it as groups of
consolidation candidates. It is deterministic (plain AST analysis, no LLM)
and fast enough to run on every invocation of the skill that sits on top
of it.

It **finds and describes** duplication. It doesn't decide what to do about
it. Where shared code should live, whether a match is worth merging, and how
to write the merged version are left to the Claude skill that consumes its
JSON output. That split shapes the design: when in doubt, slopmerge reports
a match with an honest confidence level and the evidence behind it, and
leaves the judgement to the skill.

## Goals

1. Catch identical and renamed copies with no false negatives: if two
   functions differ only in names, literals, formatting, comments or
   docstrings, they are always reported.
2. Catch copies that have drifted (statements added, removed or changed)
   and independent reimplementations of the same logic, ranked by a
   similarity score and labelled by tier, so the skill can tell solid
   matches from speculative ones.
3. Don't report code that is merely *shaped* alike. Common idioms and
   boilerplate must not crowd out real candidates (see
   [What "meaningful" means](#what-meaningful-means)).
4. Report each match as a **group** (every copy, wherever it is) rather
   than as pairs, with the evidence a reader needs: locations, what differs,
   and what the code depends on.

## Non-goals

- Deciding where consolidated code should live, or checking layering or
  import direction between repos.
- Rewriting code or proposing merged implementations.
- Semantic equivalence: two functions that compute the same thing with
  unrelated code are out of reach. The `related` tier gets partway there.
- History or trends (that's sloptrace).
- Languages other than Python.

## Relationship to sloptrace

slopmerge lives in the sloptrace repo but is an **independent package**:
it has its own `pyproject.toml`, version, CLI, tests and PyPI release, and
it does not import `sloptrace`. Where it needs the same building blocks
(file discovery, the AST normaliser, block-window hashing), it starts from a
copy of sloptrace's code, so either tool can change without breaking the
other.

```
slopmerge/
  pyproject.toml
  README.md
  SPEC.md
  python/slopmerge/
    __init__.py         # __version__
    cli.py
    discover.py         # roots -> files (adapted from sloptrace)
    units.py            # AST -> functions, classes, blocks, constant tables
    normalise.py        # the three normalisation levels
    index.py            # IDF weights, candidate generation
    match.py            # scoring, tiers, clustering
    evidence.py         # differences, parameters, dependencies
    report.py           # JSON and text output
    tests/
```

## Usage

```bash
slopmerge PATH [PATH ...]            # text summary
slopmerge PATH [PATH ...] --json     # JSON to stdout (what the skill uses)
slopmerge PATH ... -o out.json       # JSON to a file, text summary to stdout
```

Each `PATH` is a **root**: a repo, a package, or any directory. Roots are
equals: duplication is reported within any root and between any of them.
One root works too. Each root is labelled by its directory name, with
`-2`, `-3` and so on added when names collide.

| Option | Default | Meaning |
|---|---|---|
| `--units` | `functions,blocks,classes,constants` | Which unit types to match. |
| `--min-similarity` | `0.6` | Lowest similarity reported for the `near` and `related` tiers. |
| `--no-related` | off | Skip the `related` (vocabulary-based) tier. |
| `--min-statements` | `3` | Smallest function or block considered, after boilerplate is removed. |
| `--cross-root-only` | off | Only report groups that span two or more roots. |
| `--include-tests` | off | Scan test files too (excluded by default, like sloptrace). |
| `--exclude` | sloptrace's list | Path segments to skip. |
| `--max-group-size` | `50` | Above this, a group is reported as a count plus a sample of members. |

Exit code: `0` on success whether or not anything was found, `2` on bad
arguments. Files that fail to parse are skipped and listed in the
`warnings` output.

## Units

Every unit has a root, a file, a line span, a qualified name where one
exists, and a normalised representation at each level (see below).

| Unit | What it is | Notes |
|---|---|---|
| **function** | Every `def` and `async def`, including methods and nested functions. | The main consolidation unit. The docstring is dropped before comparing. |
| **block** | A run of consecutive statements inside a body (function, method or module level), at least `--min-statements` long. | Catches duplicated logic inside otherwise different functions ("extract a helper"). Blocks covered by a matched function group are dropped. |
| **class** | A `class` definition, compared on its methods and its declared fields. | Two kinds of match. *Behavioural*: most of the methods match pairwise. *Data shape*: the same set of fields, e.g. two dataclasses, Pydantic models or TypedDicts with the same field names (and types, where annotated). |
| **constant** | A literal list, tuple, set or dict made only of constants (strings, numbers, booleans, `None`), at least 3 elements, or a module-level assignment of one. | Column lists, choice tables, config maps. Sets and dict keys are compared ignoring order. |

## Normalisation levels

Each function and block is reduced to a sequence of normalised statements,
at three levels of strictness.

| Level | Erases | Keeps |
|---|---|---|
| **N0, exact** | Formatting, comments, docstrings, type annotations. | Everything else. |
| **N1, renamed** | Local identifiers (variables, parameters), literal values. | Attribute names, the names of called functions, operators, control flow. This is sloptrace's `_Normaliser`: keeping what's *called* means `x.append(y)` and `x.update(y)` don't match. |
| **N2, vocabulary** | Statement structure and order. | A bag of "tokens of intent": called names, attribute names, imported modules used, string literals, exception types raised and caught. |

A normalised statement includes only its own header. An `if` contributes
its test, not its body; the body's statements come after it in the
sequence, in pre-order. This keeps sequences comparable when code has been
re-nested.

## Tiers

Every reported group has exactly one tier. A group's tier is the strictest
one that all of its members satisfy pairwise.

| Tier | Rule | Confidence |
|---|---|---|
| `exact` | Identical N0 sequences. | Certain. |
| `renamed` | Identical N1 sequences. | Certain that the structure is the same. Literal or name differences are listed as parameters. |
| `near` | Weighted similarity of the N1 sequences ≥ `--min-similarity` (see Scoring). | High at ≥0.85, medium below that. |
| `related` | N1 similarity is below the threshold, but weighted N2 similarity ≥ `--min-similarity` and sizes are within 2× of each other. | Low: they use the same APIs in a similar amount of code. Candidates for the skill to read and verify. |

`exact` and `renamed` are found by hashing, so nothing can be missed.
`near` and `related` go through candidate generation and are only as good
as that step (see Performance).

## Scoring

Two functions or blocks, `a` and `b`, are scored on their N1 statement
sequences:

```
sim(a, b) = 2 · W(LCS(a, b)) / (W(a) + W(b))
```

- `LCS` is the longest common subsequence of normalised statements. Order
  matters, unlike sloptrace's old Jaccard over statement sets, so code
  doing the same operations in a different order scores lower.
- `W(s)` is the summed **IDF weight** of the statements in `s`, where
  `idf(stmt) = log(N / df(stmt))`, `N` is the number of functions across
  all roots, and `df` is how many of them contain that normalised statement.
  A `self.x = x` line that appears in 400 `__init__`s carries almost no
  weight, while a statement that appears in 3 functions carries a lot.

The N2 (`related`) score is the IDF-weighted Jaccard of the two token bags.

A group's `similarity` is reported as `{min, max}` over the member pairs
that were scored.

## What "meaningful" means

These rules keep reports to matches worth a reader's time. Each rule is
applied before scoring, and each has a test fixture.

1. **IDF weighting** (above) is the general mechanism: anything that is
   everywhere counts for little. It adapts to each codebase's own idioms,
   so a project-specific pattern repeated in 200 places doesn't flood the
   output.
2. **Minimum size**, measured *after* dropping docstrings, `pass`, `...`
   and bare `return`: at least `--min-statements` statements, **and** a
   total weight `W` above a floor. The floor is set so that a function made
   only of near-ubiquitous statements doesn't qualify on statement count
   alone.
3. **Known boilerplate is excluded as a unit** (it can still appear inside a
   larger match):
   - bodies that only `raise NotImplementedError`, or are abstract methods;
   - trivial delegation, i.e. a single `return` of a call that forwards the
     arguments;
   - property getters and setters that only read or assign one attribute;
   - `__init__` methods that only assign parameters to `self` (these are
     covered by the class data-shape match instead);
   - `__repr__`, `__eq__` and `__hash__` built only from attribute lists;
   - generated files: `*_pb2.py`, `*_pb2_grpc.py`, Alembic/Django
     migrations, and files with a "generated" or "do not edit" header.
4. **Subsumption**: when a whole-function group is reported, matching
   blocks inside those same functions are not reported separately. When a
   class group is reported, its method matches are listed inside it rather
   than as separate groups.
5. **Overriding methods are not boilerplate.** Several subclasses
   implementing the same method in nearly the same way is a classic
   consolidation candidate (move it to the base class), so it is reported
   as usual.

## Grouping

`exact` and `renamed` groups are hash buckets.

For `near` and `related`, pairs scoring above the threshold form a graph,
and groups are its connected components, with one safeguard against
chaining (A~B and B~C, but A and C unrelated): within a component, every
member must reach the group's **medoid** (the member with the highest total
similarity to the others) at ≥ `--min-similarity`. Members that don't are
split off and grouped again. The medoid is reported, because it is the
natural "keep this one" candidate for the skill.

## Evidence per group

Beyond locations, each group carries what the skill needs to judge it
without first re-deriving the facts from the source:

- **`differences`** (`near`, `renamed`): from the LCS alignment against the
  medoid, the statements in each member that are added, removed or changed,
  with line numbers. This tells the skill what would need to become a
  parameter or a branch.
- **`parameters`** (`renamed`, `near`): positions where the members differ
  only in a literal or a name, with the value in each member, e.g.
  `{"kind": "literal", "values": {"m1": "users", "m2": "orders"}}`. These
  are the arguments a merged function would take.
- **`uses`** per member: the module globals, imported names and `self`
  attributes it reads, and whether it is a method. This lets the skill judge
  whether a member could move somewhere shared, and what it would drag along.
- **`savings`**: an estimate of the lines removed by keeping one copy (total
  SLOC of the members minus the largest). Used for ordering, not presented
  as a promise.

## Output

### JSON

```json
{
  "schema_version": 1,
  "tool": {"name": "slopmerge", "version": "0.1.0"},
  "settings": {"min_similarity": 0.6, "min_statements": 3, "units": ["functions", "blocks", "classes", "constants"]},
  "roots": [{"label": "api", "path": "/abs/path/api", "files": 182}],
  "groups": [
    {
      "id": "g1",
      "unit": "function",
      "tier": "near",
      "similarity": {"min": 0.81, "max": 0.93},
      "cross_root": true,
      "roots": ["api", "worker"],
      "savings": 54,
      "medoid": "m1",
      "members": [
        {"id": "m1", "root": "api", "file": "api/db.py", "qualname": "fetch_rows",
         "lines": [12, 40], "sloc": 27, "is_method": false,
         "uses": {"imports": ["sqlalchemy.text"], "globals": ["ENGINE"], "self_attrs": []}},
        {"id": "m2", "root": "worker", "file": "worker/store.py", "qualname": "Store.load",
         "lines": [88, 119], "sloc": 30, "is_method": true,
         "uses": {"imports": ["sqlalchemy.text"], "globals": [], "self_attrs": ["engine"]}}
      ],
      "pairs": [{"a": "m1", "b": "m2", "similarity": 0.81}],
      "parameters": [{"kind": "literal", "values": {"m1": "users", "m2": "jobs"}, "lines": {"m1": 15, "m2": 92}}],
      "differences": [{"member": "m2", "change": "added", "lines": [101, 104]}],
      "children": []
    }
  ],
  "stats": {"files": 412, "units": {"function": 3120, "block": 0, "class": 240, "constant": 95}, "groups_by_tier": {"exact": 4, "renamed": 9, "near": 21, "related": 12}},
  "warnings": []
}
```

- `file` is relative to its root. `lines` are inclusive and 1-based.
- `children` holds subsumed matches: a class group's method matches.
- `pairs` is omitted for `exact` and `renamed` (every pair is 1.0).
- Groups are sorted by tier (`exact` → `related`), then by `savings`
  descending, then by first location. The same input always gives the same
  output, byte for byte.
- Any change to the schema bumps `schema_version`.

### Text

A summary for humans: counts by tier and unit, then the top groups per tier
(locations, similarity, savings), and a pointer to `--json` for the rest.
It is not a stable interface.

## Performance

- **Target**: 200k SLOC across all roots in under 30 seconds on a laptop,
  single process. Files are parsed in parallel, using one process per CPU.
- **Candidate generation**: scoring every pair is quadratic, so `near` and
  `related` candidates come from an inverted index. Each unit is indexed
  under its *rarest* k normalised statements (or tokens, for N2), and only
  units sharing at least one index key are scored. Statements whose `df` is
  above a cap aren't used as keys; this is the same trick as sloptrace's
  old `_MAX_DOC_FREQ`. A cheap upper bound on `sim` from the two weights
  rules out most pairs before the LCS is computed.
- LCS is computed on statement sequences, not tokens, so sequences are
  short (tens of entries), and quadratic LCS per pair is fine.

## Testing

- **Unit tests** per module, as in sloptrace.
- **A labelled fixture corpus**, `tests/corpus/`, of small files with an
  expectations file listing the groups that must be found and the pairs
  that must *not* match:
  - positives: verbatim copies; renamed copies; copies with 1–3 statements
    added, removed or edited; reordered independent statements; a loop
    rewritten as a comprehension (expected `related`, not `near`); the same
    method overridden in several subclasses; duplicated blocks inside
    different functions; two dataclasses with the same fields; the same
    column list in three modules;
  - negatives: property boilerplate; `__init__` assignment lists; one-line
    delegations; functions with the same silhouette but different
    operations (`append` and `update`); unrelated functions that both use
    `logging` heavily; generated `_pb2` files.

  The test asserts there are no missed `exact`/`renamed` matches, and
  measures precision and recall for `near` against fixed floors so a
  scoring change can't silently regress.
- **Determinism**: running twice gives byte-identical JSON.
- **Real-repo check** before each release: run on two or three real
  codebases and review the top 20 groups by hand.

## Packaging and release

- PyPI name `slopmerge`, own version (starts at `0.1.0`), Python ≥3.9, no
  runtime dependencies beyond the standard library.
- **Release tags are prefixed per package**: `slopmerge-v0.1.0`, and
  sloptrace switches to `sloptrace-v…`. The publish workflow is split in
  two, each triggered by its own tag prefix and building from its own
  directory. PyPI trusted publishing needs a second publisher registered
  for `slopmerge`.
- CI runs both packages' test suites.

## Milestones

1. Package scaffold, discovery, function units, `exact` and `renamed`
   tiers, JSON output.
2. IDF weights, candidate index, `near` tier, grouping, `differences` and
   `parameters`.
3. Boilerplate rules and the fixture corpus with precision and recall floors.
4. Blocks, constants and classes.
5. `related` tier and `uses`.
6. Text report, performance pass, packaging, release workflow.

## Open questions

- **Name.** `slopmerge` is a placeholder.
- **Default output.** The spec says text by default and `--json` for the
  skill. JSON by default would make sense if the skill is the main user.
- **Tests.** Excluded by default (as in sloptrace), but duplicated test
  helpers and fixtures are a real consolidation target. Should the skill
  scan tests in a separate pass?
