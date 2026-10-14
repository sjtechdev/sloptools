"""JSON output (the stable interface) and a text summary for humans."""

from __future__ import annotations

from collections import Counter
from typing import TextIO

from sloptools import __version__
from sloptools.merge import classes, constants, evidence
from sloptools.merge.match import TIERS, Group
from sloptools.merge.units import Unit, Root, Scan

SCHEMA_VERSION = 1
TEXT_TOP_N = 20


def _member(f: Unit, mid: str, variant: int, shape: int, similarity: float) -> dict:
    out = {"id": mid, "root": f.root, "file": f.rel, "qualname": f.qualname,
           "lines": [f.lo, f.hi], "sloc": f.sloc, "is_method": f.is_method,
           "variant": variant, "shape": shape, "similarity": similarity}
    if f.kind == "constant":
        out["entries"] = len(constants.elements(f.nodes[0]))
    if f.kind == "class":
        out["fields"] = list(f.fields)
    return out


def _parameters(g: Group, shown: list[Unit], ids: list[str], medoid: int, alignment) -> list[dict]:
    if g.tier == "exact":
        return []
    if g.unit == "class":
        return classes.parameters(shown, ids)
    if g.unit == "constant":
        return constants.parameters(shown, ids) if g.tier == "renamed" else []
    return evidence.parameters(shown, ids, medoid, alignment)


def _differences(g: Group, shown: list[Unit], ids: list[str], medoid: int, alignment, picked) -> list[dict]:
    if g.tier != "near":
        return []
    if g.unit == "class":
        return classes.differences(ids, medoid, [g.profiles[i] for i in picked], [g.method_names[i] for i in picked])
    if g.unit == "constant":
        return constants.differences(shown, ids, medoid)
    return evidence.differences(shown, ids, medoid, alignment)


def _group(g: Group, gid: str, max_size: int) -> dict:
    # a truncated group still lists its medoid, in place of the last member shown
    picked = list(range(min(max_size, len(g.members))))
    if g.medoid not in picked:
        picked[-1] = g.medoid
    shown = [g.members[i] for i in picked]
    ids = [f"m{i}" for i in range(1, len(shown) + 1)]
    medoid = picked.index(g.medoid)
    alignment = [g.alignment[i] for i in picked]
    lo, hi = g.similarity_range
    out = {
        "id": gid,
        "unit": g.unit,
        "tier": g.tier,
        "similarity": {"min": lo, "max": hi},
        "cross_root": len(g.roots) > 1,
        "roots": g.roots,
        "savings": g.savings,
        "medoid": ids[medoid],
        "member_count": len(g.members),
        "members": [_member(g.members[p], i, g.variants[p], g.shapes[p], g.similarity[p])
                    for p, i in zip(picked, ids)],
        "parameters": _parameters(g, shown, ids, medoid, alignment),
        "differences": _differences(g, shown, ids, medoid, alignment, picked),
        "children": [_group(c, f"{gid}.{j}", max_size) for j, c in enumerate(g.children, 1)],
    }
    if len(shown) < len(g.members):
        out["truncated"] = True
    return out


def to_json(roots: list[Root], scan: Scan, groups: list[Group], subsumed: int, settings: dict,
            max_group_size: int) -> dict:
    by_tier = Counter(g.tier for g in groups)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "slopmerge", "version": __version__},
        "settings": settings,
        "roots": [{"label": r.label, "path": str(r.path), "files": scan.files[r.label]} for r in roots],
        "groups": [_group(g, f"g{i}", max_group_size) for i, g in enumerate(groups, 1)],
        "stats": {
            "files": sum(scan.files.values()),
            "units": {"function": len(scan.functions), "statement_lists": len(scan.bodies),
                      "constant": len(scan.constants), "class": len(scan.classes)},
            "groups_by_tier": {t: by_tier.get(t, 0) for t in TIERS},
            "subsumed": subsumed,
            "skipped": {"generated_files": scan.generated,
                        "boilerplate_functions": dict(sorted(scan.boilerplate.items()))},
        },
        "warnings": scan.warnings,
    }


def _location(m: dict) -> str:
    return f"{m['root']}:{m['file']}:{m['lines'][0]}-{m['lines'][1]}"


def print_text(result: dict, out: TextIO) -> None:
    w = out.write
    stats = result["stats"]
    groups = result["groups"]
    w(f"\nslopmerge  {len(result['roots'])} root(s), {stats['files']} files, "
      f"{stats['units']['function']} functions, {stats['units']['statement_lists']} statement lists, "
      f"{stats['units']['constant']} constant tables, {stats['units']['class']} classes\n")
    counts = ", ".join(f"{n} {t}" for t, n in stats["groups_by_tier"].items())
    w(f"           {len(groups)} duplicate group(s): {counts}; "
      f"~{sum(g['savings'] for g in groups)} lines removable\n")

    for g in groups[:TEXT_TOP_N]:
        roots = ", ".join(g["roots"])
        sim = f"{g['similarity']['min']:.0%}-{g['similarity']['max']:.0%} similar, " if g["tier"] == "near" else ""
        unit = "" if g["unit"] == "function" else f" {g['unit']}"
        w(f"\n{g['tier'].upper() + unit:<14} {g['member_count']} copies, {sim}~{g['savings']} lines   [{roots}]\n")
        for m in g["members"]:
            mark = "*" if m["id"] == g["medoid"] else " "
            pct = f"{m['similarity']:>5.0%}" if g["tier"] == "near" else ""
            where = m["qualname"] if g["unit"] == "function" else f"in {m['qualname']}"
            w(f"  {mark} {_location(m):<60} {pct} {where}\n")
        if g.get("truncated"):
            w(f"    ... {g['member_count'] - len(g['members'])} more\n")
        params = [p for p in g["parameters"] if p["kind"] != "rename"]
        for p in params[:3]:
            vals = " / ".join(repr(v) for v in p["values"].values())
            w(f"    differs ({p['kind']}): {vals}\n")
        if len(params) > 3:
            w(f"    ... {len(params) - 3} more differing value(s)\n")
        if g["children"]:
            w(f"    {len(g['children'])} method group(s) inside; see 'children' in --json\n")
        if g["differences"]:
            if g["unit"] == "class":
                w(f"    fields or methods differ between copies; see --json\n")
            elif g["unit"] == "constant":
                n = sum(len(d["values"]) for d in g["differences"])
                w(f"    {n} entr(y/ies) added or removed between copies; see --json\n")
            else:
                w(f"    {len(g['differences'])} statement run(s) added, removed or changed; see --json\n")
    if len(groups) > TEXT_TOP_N:
        w(f"\n... {len(groups) - TEXT_TOP_N} more group(s); see --json\n")
    if groups:
        w("\n  * = the most common variant, the natural one to keep\n")
    skipped = stats["skipped"]
    n_boiler = sum(skipped["boilerplate_functions"].values())
    if n_boiler or skipped["generated_files"]:
        w(f"\n  not considered: {n_boiler} boilerplate function(s), "
          f"{len(skipped['generated_files'])} generated file(s); see 'stats.skipped' in --json\n")
    if result["warnings"]:
        w(f"\n  {len(result['warnings'])} file(s) skipped; see 'warnings' in --json\n")
    w("\n")
