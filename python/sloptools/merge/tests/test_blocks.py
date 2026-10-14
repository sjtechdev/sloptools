from __future__ import annotations

RETRY = """
    for attempt in range(retries):
        try:
            result = client.call(endpoint)
            break
        except TimeoutError:
            client.wait(attempt)
"""


def _fn(name: str, before: str, block: str, after: str) -> str:
    return f"\ndef {name}(client, retries):\n{before}{block}{after}"


# enough of their own logic around a shared block that the functions as a
# whole aren't near copies of each other
OWN_A = """    if client.closed:
        raise RuntimeError("closed")
    session = client.sessions.new(user=client.user)
    session.scope = ["read", "write"]
"""
OWN_B = """    totals = {k: 0 for k in client.keys}
    for key in client.keys:
        totals[key] += client.weight(key)
    client.limit = max(totals.values())
"""


def blocks(out):
    return [g for g in out["groups"] if g["unit"] == "block"]


def test_block_shared_by_different_functions_is_found_and_maximal(run):
    src = (_fn("one", OWN_A + "    endpoint = client.base + '/a'\n", RETRY, "    client.close()\n")
           + _fn("two", OWN_B + "    endpoint = client.alt + '/b'\n", RETRY, "    client.close()\n"))
    [g] = blocks(run({"r": {"m.py": src}}))
    assert g["tier"] == "exact" and [m["qualname"] for m in g["members"]] == ["one", "two"]
    # the loop, extended forwards to the close() both functions share
    assert [m["lines"] for m in g["members"]] == [[9, 15], [24, 30]]


def test_block_extends_over_statements_that_differ_only_in_names(run):
    # `return session` / `return totals` match at N1, so the block takes them in
    src = (_fn("one", OWN_A + "    endpoint = client.base\n", RETRY, "    client.close()\n    return session\n")
           + _fn("two", OWN_B + "    endpoint = client.alt\n", RETRY, "    client.close()\n    return totals\n"))
    [g] = blocks(run({"r": {"m.py": src}}))
    assert g["tier"] == "renamed" and [m["lines"] for m in g["members"]] == [[9, 16], [25, 32]]


def test_name_bound_outside_the_block_is_a_reference(run):
    a = RETRY.replace("endpoint", "url_a")
    b = RETRY.replace("endpoint", "url_b")
    src = (_fn("one", OWN_A + "    url_a = client.base\n", a, "    client.close()\n")
           + _fn("two", OWN_B + "    url_b = client.alt\n", b, "    client.close()\n"))
    [g] = blocks(run({"r": {"m.py": src}}))
    assert g["tier"] == "renamed"
    [ref] = [p for p in g["parameters"] if p["kind"] == "reference"]
    assert ref["values"] == {"m1": "url_a", "m2": "url_b"}   # the helper's parameter


def test_one_big_statement_counts_as_a_block(run):
    loop = """
    for item in items:
        if item.ready:
            item.ship()
            item.notify(owner)
"""
    src = (f"\ndef a(items, owner):\n{OWN_A.replace('client', 'owner')}{loop}    return owner\n"
           f"\ndef b(items, owner):\n{OWN_B.replace('client', 'owner')}{loop}    return len(items)\n")
    [g] = blocks(run({"r": {"m.py": src}}))
    assert [m["lines"] for m in g["members"]] == [[8, 11], [20, 23]]


def test_imports_and_defs_break_blocks(run):
    header = "import os\nimport sys\nfrom pathlib import Path\n"
    defs = "\ndef f(x):\n    return x\n\ndef g(y):\n    return y\n"
    out = run({"r": {"a.py": header + defs, "b.py": header + defs}}, "--min-statements", "1")
    assert blocks(out) == []


def test_repeated_statements_are_not_copies_of_themselves(run):
    src = "\ndef f(o):\n" + "    o.push(1)\n" * 6 + "    return o\n"
    assert blocks(run({"r": {"m.py": src}})) == []


def test_runs_of_plain_stores_are_not_blocks(run):
    stores = "    self.a = a\n    self.b = b\n    self.c = None\n    self.d = []\n"
    src = (f"\nclass A:\n    def setup(self, a, b):\n{stores}        self.ready()\n"
           f"\nclass B:\n    def prepare(self, a, b):\n{stores}        self.check()\n").replace("        self.", "        self.")
    assert blocks(run({"r": {"m.py": src}})) == []


def test_blocks_inside_a_function_group_are_not_repeated(run):
    src = _fn("one", "    endpoint = client.base\n", RETRY, "    return result\n")
    out = run({"r": {"a.py": src, "b.py": src}})
    assert [g["unit"] for g in out["groups"]] == ["function"]
    assert out["stats"]["subsumed"] >= 1


def test_units_option(run):
    one = _fn("one", OWN_A + "    endpoint = client.base\n", RETRY, "    return session\n")
    two = _fn("two", OWN_B + "    endpoint = client.alt\n", RETRY, "    return totals\n")
    roots = {"m.py": one + two, "n.py": one.replace("def one", "def again")}
    assert {g["unit"] for g in run({"r1": roots})["groups"]} == {"function", "block"}
    assert {g["unit"] for g in run({"r2": roots}, "--units", "functions")["groups"]} == {"function"}
    assert {g["unit"] for g in run({"r3": roots}, "--units", "blocks")["groups"]} == {"block"}


def test_import_guards_are_not_blocks(run):
    guard = """
try:
    import yaml
    HAVE_YAML = True
except ImportError:
    yaml = None
    HAVE_YAML = False
if TYPE_CHECKING:
    from collections.abc import Iterator
"""
    out = run({"r": {"a.py": guard + "\nX = 1\n", "b.py": guard + "\nY = 2\n"}}, "--min-statements", "1")
    assert blocks(out) == []


def test_module_and_class_declarations_are_not_blocks(run):
    decl = """
    name = "Example"
    flags = re.MULTILINE | re.UNICODE
    styles = {Token.Keyword: "bold", Token.Name: BASE}
"""
    src = "\nclass A(Lexer):" + decl + "\nclass B(Lexer):" + decl
    assert blocks(run({"r": {"m.py": src}})) == []
