"""The labelled corpus in tests/corpus: what must be found, and what mustn't.

Every function in the corpus is either part of an expected group or a
negative, so any other grouping counts against precision. exact and
renamed copies must all be found; near copies are measured against floors,
so a scoring change can't quietly make matching worse.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from sloptools.merge.cli import main

CORPUS = Path(__file__).parent / "corpus"

# copies that must share a group; for exact/renamed also a shape (and for exact a
# variant). A block is named by the function it's in.
EXPECTED = [
    ("function", "exact", {"app:summarise_orders", "lib:summarise_orders"}),
    ("function", "renamed", {"app:count_active_users", "lib:count_enabled_accounts"}),
    ("function", "near", {"app:export_orders_csv", "lib:export_rows_csv", "lib:export_invoices_csv"}),
    ("function", "near", {"app:build_report_headers", "lib:make_headers"}),
    ("function", "near", {"lib:CsvExporter.export", "lib:TsvExporter.export", "lib:JsonLinesExporter.export"}),
    ("function", "near", {"app:normalise_email", "lib:clean_email"}),
    ("block", "renamed", {"app:sync_account", "lib:publish_invoice"}),
    ("block", "exact", {"app:create_project", "app:rename_team"}),
    ("constant", "exact", {"app:REPORT_COLUMNS", "lib:REPORT_COLUMNS", "lib:COLUMNS"}),
    ("constant", "renamed", {"app:RETRY_POLICY", "lib:RETRY_POLICY"}),
    ("constant", "near", {"app:ACCOUNT_COLUMNS", "lib:ACCOUNT_FIELDS"}),
]

# pairs that look alike on the surface but mustn't be grouped
APART = [
    ("app:load_page", "lib:render_page"),                           # same silhouette, other operations
    ("app:refund_order", "lib:rebuild_index"),                      # both logging-heavy
    ("app:refund_order", "app:suspend_account"),
    ("app:suspend_account", "lib:rebuild_index"),
    ("app:active_names_loop", "app:active_names_comprehension"),    # a `related` match, not `near`
    ("app:hash_password", "app:check_password"),
    ("app:OPEN_MODES", "lib:WRITE_MODES"),                           # two shared values isn't a table
]

# currently 1.0 each; a floor leaves room for tuning without hiding a regression
NEAR_RECALL_FLOOR = 0.85
PRECISION_FLOOR = 0.85


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    out = tmp_path_factory.mktemp("corpus") / "out.json"
    assert main([str(CORPUS / "app"), str(CORPUS / "lib"), "-o", str(out)]) == 0
    return json.loads(out.read_text())


def _name(m: dict) -> str:
    return f"{m['root']}:{m['qualname']}"


def _key(unit: str, name: str) -> str:
    return f"{unit}/{name}"


def _pairs(names) -> set[frozenset]:
    return {frozenset(p) for p in itertools.combinations(sorted(names), 2)}


def _group_of(result: dict) -> dict[str, dict]:
    """unit/name -> its group (a function's own group, or a block's)."""
    return {_key(g["unit"], _name(m)): g for g in result["groups"] for m in g["members"]}


@pytest.mark.parametrize("unit,tier,names", [e for e in EXPECTED if e[1] != "near"], ids=lambda x: str(x))
def test_exact_and_renamed_copies_are_all_found(result, unit, tier, names):
    by_key = _group_of(result)
    found = [by_key.get(_key(unit, n)) for n in names]
    assert None not in found and len({id(g) for g in found}) == 1, f"{unit} {names} not in one group"
    members = {_name(m): m for m in found[0]["members"]}
    assert len({members[n]["shape"] for n in names}) == 1
    if tier == "exact":
        assert len({members[n]["variant"] for n in names}) == 1


@pytest.mark.parametrize("a,b", APART)
def test_lookalikes_are_kept_apart(result, a, b):
    """Not grouped together, as functions or through a shared block."""
    for g in result["groups"]:
        names = {_name(m) for m in g["members"]}
        assert not {a, b} <= names, f"{a} and {b} grouped as {g['unit']}s"


def test_near_recall_and_overall_precision(result):
    def pairs(unit, names):
        return _pairs(_key(unit, n) for n in names)
    expected = set().union(*(pairs(u, names) for u, _, names in EXPECTED))
    expected_near = set().union(*(pairs(u, names) for u, tier, names in EXPECTED if tier == "near"))
    found = set().union(set(), *(pairs(g["unit"], (_name(m) for m in g["members"])) for g in result["groups"]))
    recall = len(found & expected_near) / len(expected_near)
    precision = len(found & expected) / len(found) if found else 1.0
    assert recall >= NEAR_RECALL_FLOOR, f"near recall {recall:.2f}: missed {expected_near - found}"
    assert precision >= PRECISION_FLOOR, f"precision {precision:.2f}: unexpected {found - expected}"


def test_generated_file_and_boilerplate_are_skipped(result):
    skipped = result["stats"]["skipped"]
    assert skipped["generated_files"] == ["lib:messages_pb2.py"]
    assert set(skipped["boilerplate_functions"]) == {
        "accessor", "attribute-dunder", "delegation", "init-assignments", "stub"}
    names = {k.split("/", 1)[1] for k in _group_of(result)}
    assert not any(n.endswith(("__init__", "__eq__", "__repr__", "__hash__", ".size", ".save")) for n in names)
