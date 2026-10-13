from __future__ import annotations

import json

import pytest

from sloptools.merge.cli import main

FN = '''
def total_{n}(items):
    acc = 0
    for item in items:
        acc += item.price
    return acc
'''

TWO = FN.format(n="a") + FN.format(n="b")


def test_output_shape(run):
    out = run({"shop": {"cart.py": TWO}})
    assert out["schema_version"] == 1
    assert out["tool"]["name"] == "slopmerge"
    assert [r["label"] for r in out["roots"]] == ["shop"]
    assert out["roots"][0]["files"] == 1
    assert out["stats"]["units"] == {"function": 2}
    assert out["stats"]["groups_by_tier"] == {"exact": 1, "renamed": 0}
    [g] = out["groups"]
    assert g["id"] == "g1" and g["unit"] == "function" and g["member_count"] == 2
    assert g["members"][0] == {"id": "m1", "root": "shop", "file": "cart.py", "qualname": "total_a",
                               "lines": [2, 6], "sloc": 5, "is_method": False, "variant": 1}


def test_root_labels_are_unique(make_roots, capsys):
    a, b = make_roots({"x/lib": {"m.py": FN.format(n="a")}, "y/lib": {"m.py": FN.format(n="b")}})
    assert main([str(a), str(b), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["label"] for r in out["roots"]] == ["lib", "lib-2"]
    assert out["groups"][0]["roots"] == ["lib", "lib-2"]


def test_overlapping_or_missing_roots_are_rejected(make_roots, tmp_path):
    [root] = make_roots({"repo": {"pkg/m.py": TWO}})
    with pytest.raises(SystemExit):
        main([str(root), str(root / "pkg")])
    with pytest.raises(SystemExit):
        main([str(root), str(root)])
    with pytest.raises(SystemExit):
        main([str(tmp_path / "nope")])


def test_tests_are_skipped_unless_asked(run):
    files = {"pkg/a.py": FN.format(n="a"), "tests/test_a.py": FN.format(n="b"), "pkg/a_test.py": FN.format(n="c")}
    assert run({"r1": files})["groups"] == []
    [g] = run({"r2": files}, "--include-tests")["groups"]
    assert [m["file"] for m in g["members"]] == ["pkg/a.py", "pkg/a_test.py", "tests/test_a.py"]


def test_unparseable_files_are_skipped_with_a_warning(run):
    out = run({"r": {"ok.py": TWO, "bad.py": "def broken(:\n"}})
    assert out["warnings"] == ["r:bad.py: skipped (SyntaxError)"]
    assert len(out["groups"]) == 1


def test_large_groups_are_truncated(run):
    src = "".join(FN.format(n=i) for i in range(5))
    [g] = run({"r": {"m.py": src}}, "--max-group-size", "3")["groups"]
    assert g["member_count"] == 5 and len(g["members"]) == 3 and g["truncated"] is True


def test_truncated_group_still_lists_its_medoid(run):
    other = FN.replace("acc = 0", "acc = 1")     # a second variant, in the same N1 group
    src = other.format(n="a") + other.format(n="b") + "".join(FN.format(n=i) for i in range(3))
    [g] = run({"r": {"m.py": src}}, "--max-group-size", "2")["groups"]
    assert [m["qualname"] for m in g["members"]] == ["total_a", "total_0"]
    assert g["medoid"] == "m2" and g["members"][1]["variant"] == 2


def test_functions_inside_match_statements_are_found(run):
    src = "match MODE:\n    case 'x':\n" + "".join(
        "        " + line + "\n" for n in "ab" for line in FN.format(n=n).splitlines())
    assert len(run({"r": {"m.py": src}})["groups"]) == 1


def test_async_and_sync_versions_do_not_match(run):
    src = FN.format(n="a") + "\nasync" + FN.format(n="b")
    assert run({"r": {"m.py": src}})["groups"] == []


def test_json_is_deterministic_and_written_with_o(make_roots, capsys, tmp_path):
    roots = [str(p) for p in make_roots({"a": {"m.py": TWO, "n.py": TWO}, "b": {"m.py": TWO}})]
    out = tmp_path / "out.json"
    assert main(roots + ["--json", "-o", str(out)]) == 0
    first = capsys.readouterr().out
    assert main(roots + ["--json"]) == 0
    assert capsys.readouterr().out == first == out.read_text()


def test_text_summary(make_roots, capsys):
    [root] = make_roots({"shop": {"cart.py": TWO}})
    assert main([str(root)]) == 0
    text = capsys.readouterr().out
    assert "1 duplicate group(s): 1 exact, 0 renamed" in text
    assert "shop:cart.py:2-6" in text and "total_a" in text
