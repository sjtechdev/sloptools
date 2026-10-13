# slopmerge: spec

> Status: draft, nothing implemented yet. Part of the `sloptools` package,
> alongside `sloptrace`.

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

slopmerge is a second tool in the `sloptools` package. It is installed with
it (`pip install sloptools`), shares its version and release, and gets its
own command, `slopmerge`, next to `sloptrace`.

The two tools share code through `sloptools.common` rather than importing
each other. The building blocks both need move there out of
`sloptools.trace` as part of milestone 1: file discovery and exclusion rules,
the AST normaliser (`_Normaliser`, `body_fingerprint`), and block-window
hashing. sloptrace's behaviour must not change as a result; its existing
tests guard that.

```
python/sloptools/
  __init__.py           # __version__, shared by every tool
  common/
    discover.py         # roots -> files, exclusion rules
    normalise.py        # AST normalisation shared by both tools
  trace/                # sloptrace
  merge/                # slopmerge
    cli.py
    units.py            # AST -> functions, classes, blocks, constant tables
    levels.py           # N0/N1/N2 statement sequences, built on common.normalise
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
re-nested. The sequence starts with the function's signature, and markers
(`<else>`, `<elif>`, `<finally>`) show where those branches begin. `pass`,
`...` and bare `return` are left out.

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
  `idf(stmt) = ln((1 + N) / (1 + df(stmt))) + 1`, `N` is the number of
  distinct N1 forms (shapes) across all roots, and `df` is how many of them
  contain that normalised statement. A `self.x = x` line that appears in 400
  `__init__`s weighs about 1, while a statement that appears in 3 functions
  weighs several times that. The IDF is smoothed because plain
  `log(N / df)` gives a statement shared by every unit a weight of 0, which
  breaks small inputs: with two functions, everything they share is
  "everywhere". Counting shapes rather than functions stops a function
  copied ten times from discounting its own statements.

The N2 (`related`) score is the IDF-weighted Jaccard of the two token bags.

Each member's `similarity` is its score against the group's medoid, and a
group's `similarity` is the `{min, max}` of those, leaving out the medoid.

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

Functions with equal N1 forms form a **shape**. They are certain copies of
each other, so shapes, not functions, are what gets scored. A shape with
two or more functions, and no near neighbours, is an `exact` or `renamed`
group (a hash bucket).

For `near`, shape pairs scoring at or above the threshold form a graph, and
groups are its connected components. A near group takes in every function
of its shapes, so exact or renamed copies inside it are not reported again
as their own group. Members carry `shape` and `variant` numbers to show
which of them are renamed or verbatim copies of each other. Two safeguards
apply:

- **Chaining** (A~B and B~C, but A and C unrelated): within a component,
  every shape must score at or above the threshold against the group's
  **medoid**, the shape with the highest total similarity to the other
  functions. Shapes that don't are split off and grouped again. The medoid
  is reported (the first copy of its most common variant), because it is
  the natural "keep this one" candidate for the skill.
- **Nesting**: a function and a function nested inside it share statements
  by construction, but they aren't copies of each other. They are never
  scored against each other, and never end up in the same group: shapes
  join the medoid's group closest first, skipping any that nest with a
  member already in it.

## Evidence per group

Beyond locations, each group carries what the skill needs to judge it
without first re-deriving the facts from the source:

- **`differences`** (`near`): from each member's LCS alignment onto the
  medoid, the runs of statements between matched ones: `added` (only in the
  member, with its `lines`), `removed` (only in the medoid, with
  `medoid_lines`), or `changed` (both, in the same place). This tells the
  skill what would need to become a parameter or a branch.
- **`parameters`** (`renamed`, `near`): positions in matched statements
  where the members differ only in a literal or a name, with the value and
  line in each member (members whose copy of that statement is missing are
  left out of the entry), e.g.
  `{"kind": "literal", "values": {"m1": "users", "m2": "orders"}, ...}`.
  The same difference repeated is reported once, with a `count`. `kind` is
  one of:
  - `literal`: a constant differs. This is an argument a merged function
    would take.
  - `reference`: a name that, in at least one member, comes from outside
    the function (a module constant, a class, a helper) differs. This is
    also an argument, or a dependency to inject.
  - `rename`: a name every member binds itself (a parameter, a local)
    differs. This is cosmetic, and no argument is needed.
- **`variant`** and **`shape`** per member: members with the same N0 form
  share a variant number, and members with the same N1 form share a shape
  number, so a group shows which copies are verbatim and which are renamed
  copies of each other.
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
  "tool": {"name": "slopmerge", "version": "0.3.0"},
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
      "member_count": 2,
      "members": [
        {"id": "m1", "root": "api", "file": "db.py", "qualname": "fetch_rows",
         "lines": [12, 40], "sloc": 27, "is_method": false, "variant": 1, "shape": 1, "similarity": 1.0,
         "uses": {"imports": ["sqlalchemy.text"], "globals": ["ENGINE"], "self_attrs": []}},
        {"id": "m2", "root": "worker", "file": "store.py", "qualname": "Store.load",
         "lines": [88, 119], "sloc": 30, "is_method": true, "variant": 2, "shape": 2, "similarity": 0.81,
         "uses": {"imports": ["sqlalchemy.text"], "globals": [], "self_attrs": ["engine"]}}
      ],
      "parameters": [{"kind": "literal", "values": {"m1": "users", "m2": "jobs"}, "lines": {"m1": 15, "m2": 92}, "count": 1}],
      "differences": [{"member": "m2", "change": "added", "lines": [101, 104]},
                      {"member": "m2", "change": "changed", "lines": [110, 110], "medoid_lines": [30, 31]}],
      "children": []
    }
  ],
  "stats": {"files": 412, "units": {"function": 3120, "block": 0, "class": 240, "constant": 95}, "groups_by_tier": {"exact": 4, "renamed": 9, "near": 21, "related": 12}, "subsumed": 7},
  "warnings": []
}
```

- `file` is relative to its root. `lines` are inclusive and 1-based.
- `children` holds subsumed matches: a class group's method matches.
- A group with more than `--max-group-size` members lists only that many,
  with `"truncated": true`. `member_count` is always the full count.
- `stats.subsumed` counts groups dropped by the subsumption rule.
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
- **Candidate generation**: scoring every pair is quadratic, so `near`
  candidates come from an inverted index built by **prefix filtering**,
  which provably misses no pair at or above the threshold. If
  `sim(a, b) ≥ t`, the weight `a` and `b` share is at least
  `t · W(a) / (2 − t)`, because it can't exceed `W(b)`. Ordering every
  statement occurrence rarest first, `a`'s shortest prefix whose remaining
  weight is below that bound must share an occurrence with `b`'s prefix.
  Units are indexed under their prefix only, and only units sharing a key
  are considered. Two cheap bounds, on relative size and on bag-of-statement
  overlap, then rule out most of those before an LCS is computed. A
  randomised test checks the no-miss property against brute force.
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

- Ships in `sloptools` as a second console script,
  `slopmerge = "sloptools.merge.cli:main"`. It uses the package version
  (`tool.version` in the JSON output is `sloptools.__version__`), and the
  first release to include it is a minor bump. No release-process changes
  are needed.
- `sloptools.merge` uses only the standard library. sloptrace's `radon` and
  `complexipy` dependencies stay confined to `sloptools.trace`.
- The README gains a slopmerge row in the tools table and its own section.

## Milestones

1. Move the shared building blocks into `sloptools.common` (sloptrace's tests
   still pass, unchanged). Then the `sloptools.merge` scaffold and
   `slopmerge` command, function units, `exact` and `renamed` tiers, and
   JSON output.
2. IDF weights, candidate index, `near` tier, grouping, `differences` and
   `parameters`.
3. Boilerplate rules and the fixture corpus with precision and recall floors.
4. Blocks, constants and classes.
5. `related` tier and `uses`.
6. Text report, performance pass, README.
