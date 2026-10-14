from __future__ import annotations


def constants(out):
    return [g for g in out["groups"] if g["unit"] == "constant"]


def test_same_list_in_several_modules_is_exact_and_named(run):
    cols = '["id", "name", "email", "created"]'
    out = run({"r": {"a.py": f"COLUMNS = {cols}\n",
                     "b.py": f"class View:\n    columns = {cols}\n",
                     "c.py": f"def load(db):\n    return db.select({cols})\n"}})
    [g] = constants(out)
    assert g["tier"] == "exact"
    assert [m["qualname"] for m in g["members"]] == ["COLUMNS", "View.columns", "load"]
    assert all(m["entries"] == 4 for m in g["members"])


def test_lists_and_tuples_compare_in_order_sets_without(run):
    out = run({"r": {"a.py": 'A = ["x", "y", "z", "w"]\nB = ("x", "y", "z", "w")\n'
                              'C = {"w", "z", "y", "x"}\nD = {"x", "y", "z", "w"}\n'
                              'E = ["w", "z", "y", "x"]\n'}})
    # the same four entries throughout, so one group; shapes tell the forms apart
    [g] = constants(out)
    assert g["tier"] == "near" and g["similarity"] == {"min": 1.0, "max": 1.0}
    shape = {m["qualname"]: m["shape"] for m in g["members"]}
    assert shape["A"] == shape["B"]        # list and tuple, same order
    assert shape["C"] == shape["D"]        # sets, order ignored
    assert len({shape["A"], shape["C"], shape["E"]}) == 3   # E is a list in another order


def test_dicts_with_the_same_keys_are_renamed_with_values_as_parameters(run):
    out = run({"r": {"a.py": 'POLICY = {"tries": 3, "wait": 1.0, "cap": 30}\n',
                     "b.py": 'POLICY = {"cap": 60, "tries": 3, "wait": 2.0}\n'}})
    [g] = constants(out)
    assert g["tier"] == "renamed"
    # in the first copy's order; "tries" is the same in both
    assert [(p["key"], p["values"]) for p in g["parameters"]] == [
        ("wait", {"m1": 1.0, "m2": 2.0}), ("cap", {"m1": 30, "m2": 60})]


def test_near_lists_report_the_entries_that_differ(run):
    out = run({"r": {"a.py": 'COLS = ["id", "name", "email", "phone", "city"]\n',
                     "b.py": 'COLS = ["id", "name", "email", "phone", "zip"]\n'}})
    [g] = constants(out)
    assert g["tier"] == "near"
    assert sorted((d["change"], d["values"]) for d in g["differences"]) == [("added", ["zip"]), ("removed", ["city"])]


def test_small_or_repetitive_literals_are_ignored(run):
    out = run({"r": {"a.py": 'A = (0, 0, 0)\nB = ["x", "y"]\n__all__ = ["f", "g", "h"]\n',
                     "b.py": 'A = (0, 0, 0)\nB = ["x", "y"]\n__all__ = ["f", "g", "h"]\n'}})
    assert constants(out) == []


def test_tables_sharing_only_two_entries_are_not_near(run):
    out = run({"r": {"a.py": 'M = ("r", "rb", "w")\n', "b.py": 'M = ("r", "rb", "x")\n'}})
    assert constants(out) == []


def test_nested_literals_are_one_table(run):
    choices = '[("draft", "Draft"), ("live", "Live"), ("gone", "Archived")]'
    out = run({"r": {"a.py": f"class Post:\n    STATUS = {choices}\n", "b.py": f"class Page:\n    STATUS = {choices}\n"}})
    [g] = constants(out)       # the whole table, not each pair inside it
    assert [m["qualname"] for m in g["members"]] == ["Post.STATUS", "Page.STATUS"]


def test_constants_inside_duplicated_functions_are_not_repeated(run):
    src = 'def load(db):\n    cols = ["id", "name", "email"]\n    rows = db.select(cols)\n    rows.sort()\n    return rows\n'
    out = run({"r": {"a.py": src, "b.py": src}})
    assert [g["unit"] for g in out["groups"]] == ["function"]
