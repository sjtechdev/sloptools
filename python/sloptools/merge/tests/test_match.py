from __future__ import annotations

FETCH = '''
def fetch_rows(engine, limit):
    """Fetch rows."""
    rows = engine.execute("select * from users")
    out = []
    for row in rows[:limit]:
        out.append(row.to_dict())
    return out
'''

# same code: different formatting, comments, docstring, annotations, decorator
FETCH_RESTYLED = '''
import functools

@functools.cache
def fetch_rows(engine: "Engine", limit: int) -> list:
    # grab everything
    rows = engine.execute(
        "select * from users"
    )
    out: list = []
    for row in rows[:limit]:
        out.append(row.to_dict())
    return out
'''

# same code with renamed locals and a different literal
FETCH_RENAMED = '''
def load_jobs(db, n):
    result = db.execute("select * from jobs")
    acc = []
    for r in result[:n]:
        acc.append(r.to_dict())
    return acc
'''

# same shape, different operation: update instead of append
FETCH_OTHER_OP = '''
def load_jobs(db, n):
    result = db.execute("select * from jobs")
    acc = []
    for r in result[:n]:
        acc.update(r.to_dict())
    return acc
'''


def groups(result):
    return result["groups"]


def locations(group):
    return [(m["root"], m["file"], m["qualname"]) for m in group["members"]]


def test_exact_copy_across_roots_ignores_formatting_comments_docstrings_annotations(run):
    out = run({"api": {"db.py": FETCH}, "worker": {"store.py": FETCH_RESTYLED}})
    [g] = groups(out)
    assert g["tier"] == "exact"
    assert g["cross_root"] is True and g["roots"] == ["api", "worker"]
    assert locations(g) == [("api", "db.py", "fetch_rows"), ("worker", "store.py", "fetch_rows")]
    assert g["parameters"] == []
    assert g["similarity"] == {"min": 1.0, "max": 1.0}


def test_renamed_copy_reports_the_literal_that_differs(run):
    out = run({"api": {"db.py": FETCH}, "worker": {"jobs.py": FETCH_RENAMED}})
    [g] = groups(out)
    assert g["tier"] == "renamed"
    [literal] = [p for p in g["parameters"] if p["kind"] == "literal"]
    assert literal["values"] == {"m1": "select * from users", "m2": "select * from jobs"}
    assert literal["lines"] == {"m1": 4, "m2": 3}
    # parameter and local renames are cosmetic, not arguments a merge would need
    assert {p["kind"] for p in g["parameters"]} == {"literal", "rename"}


def test_different_called_class_is_not_a_renamed_copy(run):
    src = '''
    def make_{n}(a, b):
        x = a + b
        y = x * 2
        return {cls}(x, y)
    '''
    out = run({"r": {"m.py": src.format(n="one", cls="One") + src.format(n="two", cls="Two")}})
    assert groups(out) == []


def test_reference_kind_for_passed_global(run):
    src = '''
    def check_{n}(value):
        if value is None:
            raise ValueError("missing")
        return validate(value, {table})
    '''
    out = run({"r": {"m.py": src.format(n="a", table="USERS") + src.format(n="b", table="JOBS")}})
    [g] = groups(out)
    [ref] = [p for p in g["parameters"] if p["kind"] == "reference"]
    assert ref["values"] == {"m1": "USERS", "m2": "JOBS"}


def test_same_shape_different_operation_does_not_match(run):
    out = run({"api": {"db.py": FETCH}, "worker": {"jobs.py": FETCH_OTHER_OP}})
    assert groups(out) == []


def test_small_functions_are_ignored(run):
    tiny = '''
    def get_{n}(self):
        """Docstrings, pass and bare return don't count."""
        x = self.value
        pass
        return x
    '''
    out = run({"r": {"m.py": tiny.format(n="a") + tiny.format(n="b")}})
    assert groups(out) == []
    out = run({"r2": {"m.py": tiny.format(n="a") + tiny.format(n="b")}}, "--min-statements", "2")
    assert len(groups(out)) == 1


def test_methods_get_qualnames_and_is_method(run):
    cls = '''
    class {c}:
        def run(self, items):
            total = 0
            for i in items:
                total += i.weight
            return total
    '''
    out = run({"r": {"m.py": cls.format(c="A") + cls.format(c="B")}})
    [g] = groups(out)
    assert [(m["qualname"], m["is_method"]) for m in g["members"]] == [("A.run", True), ("B.run", True)]


def test_nested_function_copied_with_its_parent_is_subsumed(run):
    outer = '''
    def outer_{n}(items):
        def score(x):
            a = x.weight
            b = x.size
            return a * b
        ranked = sorted(items, key=score)
        return ranked[:10]
    '''
    out = run({"r": {"m.py": outer.format(n="a") + outer.format(n="b")}})
    [g] = groups(out)
    assert [m["qualname"] for m in g["members"]] == ["outer_a", "outer_b"]
    assert out["stats"]["subsumed"] == 1


def test_cross_root_only(run):
    roots = {"a": {"x.py": FETCH, "y.py": FETCH}, "b": {"z.py": FETCH_RENAMED}}
    assert len(groups(run(roots))) == 1
    roots2 = {"c": {"x.py": FETCH, "y.py": FETCH}, "d": {"z.py": FETCH_OTHER_OP}}
    assert groups(run(roots2, "--cross-root-only")) == []


def test_variants_and_medoid_pick_the_most_common_form(run):
    out = run({"r": {"a.py": FETCH_RENAMED, "b.py": FETCH, "c.py": FETCH, "d.py": FETCH_RESTYLED}})
    [g] = groups(out)
    assert [m["file"] for m in g["members"]] == ["a.py", "b.py", "c.py", "d.py"]
    assert [m["variant"] for m in g["members"]] == [1, 2, 2, 2]
    assert g["medoid"] == "m2"


def test_groups_ordered_by_tier_then_savings(run):
    small = """
def small_{n}(a):
    b = a.one()
    c = b.two()
    return c.three()
"""
    out = run({"r": {"a.py": FETCH, "b.py": FETCH_RENAMED,
                     "c.py": small.format(n="x") + small.format(n="y"), "d.py": FETCH, "e.py": FETCH}})
    assert [(g["tier"], g["member_count"], g["savings"]) for g in groups(out)] == [
        ("exact", 2, 4), ("renamed", 4, 18)]
