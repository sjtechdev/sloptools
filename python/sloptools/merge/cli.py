"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sloptools.common.discover import DEFAULT_EXCLUDES
from sloptools.merge.match import find_groups
from sloptools.merge.report import print_text, to_json
from sloptools.merge.units import collect, label_roots


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="slopmerge",
                                 description="Find duplicated Python code that could be consolidated.")
    ap.add_argument("paths", nargs="+", type=Path, metavar="PATH",
                    help="roots to scan (repos, packages or directories); duplication is "
                         "reported within and between them")
    ap.add_argument("--json", action="store_true", help="print JSON instead of the text summary")
    ap.add_argument("-o", "--output", type=Path, default=None, help="also write JSON here")
    ap.add_argument("--units", default="functions,blocks,constants", metavar="LIST",
                    help="what to match, comma-separated: functions, blocks, constants (default all)")
    ap.add_argument("--min-statements", type=int, default=3, metavar="N",
                    help="smallest function or block considered, in statements (default 3)")
    ap.add_argument("--min-similarity", type=float, default=0.6, metavar="T",
                    help="lowest similarity (0-1] for a near copy (default 0.6; 1 reports only "
                         "exact and renamed copies)")
    ap.add_argument("--cross-root-only", action="store_true",
                    help="only report groups that span two or more roots")
    ap.add_argument("--include-tests", action="store_true", help="scan test files too")
    ap.add_argument("--exclude", nargs="*", default=None,
                    help="path segments to skip (replaces the defaults: %s)" % " ".join(DEFAULT_EXCLUDES))
    ap.add_argument("--max-group-size", type=int, default=50, metavar="N",
                    help="list at most N members per group (default 50)")
    return ap


def _overlap(paths: list[Path]) -> tuple[Path, Path] | None:
    for i, a in enumerate(paths):
        for b in paths[i + 1:]:
            if a == b or a in b.parents or b in a.parents:
                return a, b
    return None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = [p.resolve() for p in args.paths]
    for p in paths:
        if not p.is_dir():
            parser.error(f"{p} is not a directory")
    if clash := _overlap(paths):
        parser.error(f"roots overlap: {clash[0]} and {clash[1]}")
    if not 0 < args.min_similarity <= 1:
        parser.error("--min-similarity must be in (0, 1]")
    if args.min_statements < 1 or args.max_group_size < 2:
        parser.error("--min-statements must be at least 1 and --max-group-size at least 2")

    units = tuple(u.strip() for u in args.units.split(",") if u.strip())
    if not units or set(units) - {"functions", "blocks", "constants"}:
        parser.error("--units takes a comma-separated list of: functions, blocks, constants")

    excludes = tuple(args.exclude) if args.exclude is not None else DEFAULT_EXCLUDES
    roots = label_roots(paths)
    scan = collect(roots, excludes, args.include_tests)
    order = {r.label: i for i, r in enumerate(roots)}
    groups, subsumed = find_groups(scan, order, args.min_statements, args.min_similarity, units)
    if args.cross_root_only:
        groups = [g for g in groups if len(g.roots) > 1]

    settings = {"min_similarity": args.min_similarity, "min_statements": args.min_statements, "units": list(units),
                "cross_root_only": args.cross_root_only, "include_tests": args.include_tests,
                "excludes": list(excludes)}
    result = to_json(roots, scan, groups, subsumed, settings, args.max_group_size)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text + "\n")
    if args.json:
        sys.stdout.write(text + "\n")
    else:
        print_text(result, sys.stdout)
    return 0
