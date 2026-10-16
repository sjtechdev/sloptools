# Output

## Evidence in each group

- **`differences`** (`near`): runs of statements that differ from the
  medoid: `added`, `removed`, or `changed`, with line numbers. These are
  what would become a parameter or a branch.
- **`parameters`** (`renamed`, `near`): places where members differ only in
  a value or name. `kind` is:
  - `literal`: a constant differs; an argument a merged function would take.
  - `reference`: a name from outside the function differs (a module
    constant, a class, a helper); also an argument or injected dependency.
  - `rename`: a name every member defines itself differs; cosmetic.
- **`variant`** / **`shape`** per member: same variant means verbatim copy,
  same shape means renamed copy.
- **`uses`** per function or block: what it reads but doesn't define, as
  `imports` (shown as what they refer to, e.g. `sqlalchemy.text`),
  `globals`, `self_attrs`, and `outer` (names from an enclosing function; for
  a block, the helper's parameter list). Builtins are left out. This shows
  what would come along if a member moved somewhere shared.
- **`savings`**: estimated lines removed by keeping one copy (total SLOC
  minus the largest). Used for ordering, not a promise.

## JSON

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
         "uses": {"imports": ["sqlalchemy.text"], "globals": ["ENGINE"], "self_attrs": [], "outer": []}},
        {"id": "m2", "root": "worker", "file": "store.py", "qualname": "Store.load",
         "lines": [88, 119], "sloc": 30, "is_method": true, "variant": 2, "shape": 2, "similarity": 0.81,
         "uses": {"imports": ["sqlalchemy.text"], "globals": [], "self_attrs": ["engine"], "outer": []}}
      ],
      "parameters": [{"kind": "literal", "values": {"m1": "users", "m2": "jobs"}, "lines": {"m1": 15, "m2": 92}, "count": 1}],
      "differences": [{"member": "m2", "change": "added", "lines": [101, 104]}],
      "children": [],
      "vocabulary": ["call:.fetch_one", "str:deleted"]
    }
  ],
  "stats": {"files": 412, "groups_by_tier": {"exact": 4, "renamed": 9, "near": 21, "related": 12}, "subsumed": 7, "skipped": {}},
  "warnings": []
}
```

- `file` is relative to its root; `lines` are 1-based and inclusive.
- `children` holds a class group's method matches.
- `vocabulary` appears on `related` groups only (the tokens all members share).
- Groups over `--max-group-size` list that many members and set
  `"truncated": true`; `member_count` is always the full count.
- Groups are sorted by `savings`, then tier, then location. `related`
  groups always come last. Output is deterministic, byte for byte.
- Any schema change bumps `schema_version`.

## Text

A human summary: counts by tier and unit, then the top groups per tier. Not
a stable interface.
