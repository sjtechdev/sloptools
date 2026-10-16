# slopmerge

Finds Python code that has been copied or reimplemented, within one codebase
or across several, and reports it as groups of merge candidates. It's
deterministic (plain AST analysis, no LLM).

slopmerge **finds and describes** duplication. It doesn't decide what to do
about it: where shared code should live and whether a match is worth merging
is left to whoever reads the output (for example a Claude skill using
`--json`). When unsure, it reports the match with an honest confidence level
and the evidence.

## Usage

```bash
slopmerge PATH [PATH ...]            # text summary
slopmerge PATH [PATH ...] --json     # JSON to stdout
slopmerge PATH ... -o out.json       # JSON to a file, summary to stdout
```

Each `PATH` is a **root**: a repo, a package, any directory. Roots are
equals; duplication is reported within and between them. Roots are labelled
by directory name (`-2`, `-3` added if names collide).

| Option | Default | Meaning |
|---|---|---|
| `--units` | `functions,blocks,constants,classes` | Which kinds of code to match. |
| `--min-similarity` | `0.6` | Lowest score reported for `near` and `related`. |
| `--no-related` | off | Skip the low-confidence `related` tier. |
| `--min-statements` | `3` | Smallest function or block considered. |
| `--cross-root-only` | off | Only groups that span two or more roots. |
| `--include-tests` | off | Scan test files too. |
| `--exclude` | same as sloptrace | Path segments to skip. |
| `--max-group-size` | `50` | Larger groups list a sample of members. |

Exit code is `0` on success (even if nothing is found) and `2` on bad
arguments. Files that fail to parse are skipped and listed under `warnings`.

## Tiers

Every group has one tier: the strictest that all its members meet.

| Tier | Meaning | Confidence |
|---|---|---|
| `exact` | Same code, ignoring formatting, comments, docstrings, annotations. | Certain |
| `renamed` | Same code with different local names and literal values. | Certain |
| `near` | Same code with statements added, removed or changed. | High at 0.85+, else medium |
| `related` | Different code using the same calls, attributes and literals. | Low |

`exact` and `renamed` are found by hashing, so none are missed.

## More

- [Units](units.md): functions, blocks, constants, classes.
- [Matching](matching.md): normalisation, scoring, grouping.
- [What gets skipped](noise.md): rules that keep boilerplate out.
- [Output](output.md): JSON format and the evidence in each group.
- [Internals](internals.md): code layout, performance, tests.
