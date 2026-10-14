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


def test_different_called_class_is_a_near_copy_not_a_renamed_one(run):
    src = '''
    def make_{n}(a, b):
        x = a + b
        y = x * 2
        return {cls}(x, y)
    '''
    out = run({"r": {"m.py": src.format(n="one", cls="One") + src.format(n="two", cls="Two")}})
    [g] = groups(out)
    assert g["tier"] == "near"
    assert run({"r2": {"m.py": src.format(n="one", cls="One") + src.format(n="two", cls="Two")}},
               "--min-similarity", "1")["groups"] == []


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


def test_same_shape_different_operation_is_near_with_the_change_located(run):
    out = run({"api": {"db.py": FETCH}, "worker": {"jobs.py": FETCH_OTHER_OP}})
    [g] = groups(out)
    assert g["tier"] == "near"
    assert g["differences"] == [{"member": "m2", "change": "changed", "lines": [6, 6], "medoid_lines": [7, 7]}]


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
    assert out["stats"]["subsumed"] == 2      # score's own group, and the block that is its body


def test_cross_root_only(run):
    roots = {"a": {"x.py": FETCH, "y.py": FETCH}, "b": {"z.py": FETCH_RENAMED}}
    assert len(groups(run(roots))) == 1
    roots2 = {"c": {"x.py": FETCH, "y.py": FETCH}, "d": {"z.py": FETCH_OTHER_OP}}
    assert groups(run(roots2, "--cross-root-only", "--min-similarity", "1")) == []
    [g] = groups(run({"e": roots2["c"], "f": roots2["d"]}, "--cross-root-only"))
    assert g["tier"] == "near" and g["roots"] == ["e", "f"]


def test_variants_and_medoid_pick_the_most_common_form(run):
    out = run({"r": {"a.py": FETCH_RENAMED, "b.py": FETCH, "c.py": FETCH, "d.py": FETCH_RESTYLED}})
    [g] = groups(out)
    assert [m["file"] for m in g["members"]] == ["a.py", "b.py", "c.py", "d.py"]
    assert [m["variant"] for m in g["members"]] == [1, 2, 2, 2]
    assert g["medoid"] == "m2"


def test_groups_ordered_by_savings_then_tier(run):
    small = """
def small_{n}(a):
    b = a.one()
    c = b.two()
    return c.three()
"""
    out = run({"r": {"a.py": FETCH, "b.py": FETCH_RENAMED,
                     "c.py": small.format(n="x") + small.format(n="y"), "d.py": FETCH, "e.py": FETCH}})
    # the bigger saving comes first, even though it's the less certain tier
    assert [(g["tier"], g["member_count"], g["savings"]) for g in groups(out)] == [
        ("renamed", 4, 18), ("exact", 2, 4)]


def test_a_function_and_one_nested_inside_it_never_share_a_group(run):
    # m is close to both the nested callback and the factory around it; the
    # callback and its factory must not end up in m's group together
    src = """
def m(match):
    text = match.group(0)
    lexer.push(text)
    lexer.pos = match.end()
    return text


def make(lexer):
    def callback(match):
        text = match.group(0)
        lexer.push(text)
        lexer.pos = match.end()
        lexer.count += 1
        return text
    return callback
"""
    [g] = groups(run({"r": {"m.py": src}}))
    assert [m["qualname"] for m in g["members"]] == ["m", "make.callback"]


def _steps(name: str, steps: str) -> str:
    """A function made of distinct, rare statements: one call per step."""
    body = "".join(f"    v = step_{s}(v)\n" for s in steps.split())
    return f"\ndef {name}(v):\n{body}    return v\n"


def test_drifted_copy_is_near_with_added_and_removed_runs(run):
    # drift inserts x, y after b and drops e
    src = _steps("orig", "a b c d e f") + _steps("drift", "a b x y c d f")
    [g] = groups(run({"r": {"m.py": src}}))
    assert g["tier"] == "near" and 0.6 <= g["similarity"]["min"] < 1
    assert [m["qualname"] for m in g["members"]] == ["orig", "drift"] and g["medoid"] == "m1"
    assert g["differences"] == [
        {"member": "m2", "change": "added", "lines": [14, 15]},
        {"member": "m2", "change": "removed", "medoid_lines": [7, 7]},
    ]


def test_chained_similarity_is_split_at_the_medoid(run):
    # A~B, B~C, C~D, but A and D share almost nothing
    src = (_steps("a", "p q r s t u") + _steps("b", "r s t u v w")
           + _steps("c", "t u v w x y") + _steps("d", "v w x y z zz"))
    out = run({"r": {"m.py": src}})
    for g in groups(out):
        names = {m["qualname"] for m in g["members"]}
        assert not {"a", "d"} <= names
        assert all(m["similarity"] >= 0.6 for m in g["members"])
    functions = [g for g in groups(out) if g["unit"] == "function"]
    assert [sorted(m["qualname"] for m in g["members"]) for g in functions] == [["a", "b", "c"]]
    # c and d still share a verbatim run of four statements, reported as a block
    [block] = [g for g in groups(out) if g["unit"] == "block"]
    assert [m["qualname"] for m in block["members"]] == ["c", "d"] and block["tier"] == "exact"


def test_near_group_absorbs_renamed_copies_and_labels_their_shape(run):
    src = (_steps("one", "a b c d e") + _steps("two", "a b c d e").replace("v", "w")
           + _steps("three", "a b c d x"))
    out = run({"r": {"m.py": src}})
    [g] = groups(out)        # no separate renamed group for one/two
    assert g["tier"] == "near"
    by_name = {m["qualname"]: m for m in g["members"]}
    assert by_name["one"]["shape"] == by_name["two"]["shape"] != by_name["three"]["shape"]
    assert by_name["one"]["variant"] != by_name["two"]["variant"]
    assert by_name["one"]["similarity"] == by_name["two"]["similarity"] == 1.0


def test_parameters_of_near_copies_cover_matched_statements_only(run):
    src = '''
def load_users(db):
    rows = db.query("users")
    rows = [r for r in rows if r.active]
    db.log("loaded")
    return rows


def load_jobs(db):
    rows = db.query("jobs")
    rows = [r for r in rows if r.active]
    db.audit()
    db.log("loaded")
    return rows
'''
    [g] = groups(run({"r": {"m.py": src}}))
    assert g["tier"] == "near"
    literals = [p["values"] for p in g["parameters"] if p["kind"] == "literal"]
    assert literals == [{"m1": "users", "m2": "jobs"}]
    [d] = g["differences"]
    assert d["change"] in ("added", "removed")


def test_loop_and_comprehension_are_related_with_their_shared_vocabulary(run):
    src = '''
def names_loop(users):
    names = []
    for user in users:
        if user.state == "active":
            names.append(user.name.title())
    return sorted(names)


def names_comprehension(users):
    names = [u.name.title() for u in users if u.state == "active"]
    names.sort()
    result = list(names)
    return result
'''
    # unrelated neighbours, as any codebase has: with only two functions, everything
    # they share would look ubiquitous to the IDF weights
    others = _steps("p", "a b c") + _steps("q", "d e f") + _steps("s", "g h i")
    [g] = groups(run({"r": {"m.py": src, "other.py": others}}))
    assert g["tier"] == "related"
    assert g["vocabulary"] == ["attr:.name", "attr:.state", "call:.title", "str:active"]
    assert groups(run({"r2": {"m.py": src, "other.py": others}}, "--no-related")) == []


def test_related_needs_similar_size(run):
    # b has a's vocabulary and four times the code (arithmetic adds no vocabulary)
    body = "    x = u.name.title()\n    y = u.state == 'active'\n    z = u.email.lower()\n"
    small = f"\ndef a(u):\n{body}    return x, y, z\n"
    big = f"\ndef b(u, n):\n{body}" + "".join(f"    n = n * {i} + 1\n" for i in range(9)) + "    return x, y, z, n\n"
    others = _steps("p", "a b c") + _steps("q", "d e f") + _steps("s", "g h i")
    assert [g for g in groups(run({"r": {"m.py": small + big, "o.py": others}})) if g["tier"] == "related"] == []


def test_related_groups_come_after_the_rest(run):
    loop = "\ndef n1(users):\n    out = []\n    for u in users:\n        if u.state == 'active':\n            out.append(u.name.title())\n    return sorted(out)\n"
    comp = "\ndef n2(users):\n    out = [u.name.title() for u in users if u.state == 'active']\n    out.sort()\n    final = list(out)\n    return final\n"
    others = _steps("p", "a b c") + _steps("q", "d e f") + _steps("s", "g h i")
    out = run({"r": {"m.py": loop + comp + FETCH + FETCH_RESTYLED.replace("import functools", ""), "o.py": others}})
    assert [g["tier"] for g in groups(out)][-1] == "related"
