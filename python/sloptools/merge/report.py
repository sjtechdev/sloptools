"""JSON output (the stable interface) and a text summary for humans."""

from __future__ import annotations

from collections import Counter
from typing import TextIO

from sloptools import __version__
from sloptools.merge import evidence
from sloptools.merge.match import TIERS, Group
from sloptools.merge.units import Function, Root

SCHEMA_VERSION = 1
TEXT_TOP_N = 20


def _member(f: Function, mid: str, variant: int) -> dict:
    return {"id": mid, "root": f.root, "file": f.rel, "qualname": f.qualname,
            "lines": [f.lo, f.hi], "sloc": f.sloc, "is_method": f.is_method, "variant": variant}


def _group(g: Group, gid: str, max_size: int) -> dict:
    # a truncated group still lists its medoid, in place of the last member shown
    picked = list(range(min(max_size, len(g.members))))
    if g.medoid not in picked:
        picked[-1] = g.medoid
    shown = [g.members[i] for i in picked]
    variants = [g.variants[i] for i in picked]
    ids = [f"m{i}" for i in range(1, len(shown) + 1)]
    out = {
        "id": gid,
        "unit": "function",
        "tier": g.tier,
        "similarity": {"min": 1.0, "max": 1.0},
        "cross_root": len(g.roots) > 1,
        "roots": g.roots,
        "savings": g.savings,
        "medoid": ids[picked.index(g.medoid)],
        "member_count": len(g.members),
        "members": [_member(f, i, v) for f, i, v in zip(shown, ids, variants)],
        "parameters": [] if g.tier == "exact" else evidence.parameters(shown, ids),
        "children": [],
    }
    if len(shown) < len(g.members):
        out["truncated"] = True
    return out


def to_json(roots: list[Root], files: dict[str, int], functions: list[Function], groups: list[Group],
            subsumed: int, warnings: list[str], settings: dict, max_group_size: int) -> dict:
    by_tier = Counter(g.tier for g in groups)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "slopmerge", "version": __version__},
        "settings": settings,
        "roots": [{"label": r.label, "path": str(r.path), "files": files[r.label]} for r in roots],
        "groups": [_group(g, f"g{i}", max_group_size) for i, g in enumerate(groups, 1)],
        "stats": {
            "files": sum(files.values()),
            "units": {"function": len(functions)},
            "groups_by_tier": {t: by_tier.get(t, 0) for t in TIERS},
            "subsumed": subsumed,
        },
        "warnings": warnings,
    }


def _location(m: dict) -> str:
    return f"{m['root']}:{m['file']}:{m['lines'][0]}-{m['lines'][1]}"


def print_text(result: dict, out: TextIO) -> None:
    w = out.write
    stats = result["stats"]
    groups = result["groups"]
    w(f"\nslopmerge  {len(result['roots'])} root(s), {stats['files']} files, "
      f"{stats['units']['function']} functions\n")
    counts = ", ".join(f"{n} {t}" for t, n in stats["groups_by_tier"].items())
    w(f"           {len(groups)} duplicate group(s): {counts}; "
      f"~{sum(g['savings'] for g in groups)} lines removable\n")

    for g in groups[:TEXT_TOP_N]:
        roots = ", ".join(g["roots"])
        w(f"\n{g['tier'].upper():<8} {g['member_count']} copies, ~{g['savings']} lines   [{roots}]\n")
        for m in g["members"]:
            mark = "*" if m["id"] == g["medoid"] else " "
            w(f"  {mark} {_location(m):<60} {m['qualname']}\n")
        if g.get("truncated"):
            w(f"    ... {g['member_count'] - len(g['members'])} more\n")
        params = [p for p in g["parameters"] if p["kind"] != "rename"]
        for p in params[:3]:
            vals = " / ".join(repr(v) for v in p["values"].values())
            w(f"    differs ({p['kind']}): {vals}\n")
        if len(params) > 3:
            w(f"    ... {len(params) - 3} more difference(s)\n")
    if len(groups) > TEXT_TOP_N:
        w(f"\n... {len(groups) - TEXT_TOP_N} more group(s); see --json\n")
    if groups:
        w("\n  * = the most common variant, the natural one to keep\n")
    if result["warnings"]:
        w(f"\n  {len(result['warnings'])} file(s) skipped; see 'warnings' in --json\n")
    w("\n")
