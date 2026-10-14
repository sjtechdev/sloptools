from __future__ import annotations


def classes(out):
    return [g for g in out["groups"] if g["unit"] == "class"]


DATA = """
@dataclass
class {name}:
    street: str
    city: str
    postcode: {pc}
    country: str = "GB"
{extra}"""


def test_dataclasses_with_the_same_fields_are_exact(run):
    src = DATA.format(name="A", pc="str", extra="") + DATA.format(name="B", pc="str", extra="")
    [g] = classes(run({"r": {"m.py": src}}))
    assert g["tier"] == "exact"
    assert g["members"][0]["fields"] == ["street", "city", "postcode", "country"]


def test_a_differing_field_type_makes_them_renamed(run):
    src = DATA.format(name="A", pc="str", extra="") + DATA.format(name="B", pc="int", extra="")
    [g] = classes(run({"r": {"m.py": src}}))
    assert g["tier"] == "renamed"
    assert g["parameters"] == [{"kind": "type", "key": "postcode", "values": {"m1": "str", "m2": "int"}, "count": 1}]


def test_an_extra_field_makes_them_near(run):
    src = DATA.format(name="A", pc="str", extra="") + DATA.format(name="B", pc="str", extra="    region: str\n")
    [g] = classes(run({"r": {"m.py": src}}))
    assert g["tier"] == "near"
    assert g["differences"] == [{"member": "m2", "change": "added", "fields": ["region"]}]


def test_django_style_fields_count_but_literal_attributes_do_not(run):
    model = "\nclass {n}(models.Model):\n    name = models.CharField()\n    email = models.EmailField()\n    joined = models.DateField()\n"
    lexer = "\nclass {n}(RegexLexer):\n    name = 'X'\n    aliases = ['x']\n    filenames = ['*.x']\n    mimetypes = ['text/x']\n"
    out = run({"r": {"m.py": model.format(n="A") + model.format(n="B") + lexer.format(n="L1") + lexer.format(n="L2")}})
    assert [sorted(m["qualname"] for m in g["members"]) for g in classes(out)] == [["A", "B"]]


def test_classvars_are_not_fields(run):
    cls = "\nclass {n}:\n    a: ClassVar[int] = 1\n    b: ClassVar[str] = 'x'\n    c: typing.ClassVar[int] = 2\n"
    assert classes(run({"r": {"m.py": cls.format(n="A") + cls.format(n="B")}})) == []


METHODS = """
class {n}:
    def load(self, key):
        row = self.store.get(key)
        if row is None:
            raise KeyError(key)
        return self.decode(row)

    def drop(self, key):
        row = self.load(key)
        self.store.remove(key)
        self.log.info("dropped %s", key)
        return row
{own}"""


def test_classes_with_matching_methods_nest_the_method_groups(run):
    own_b = "\n    def audit(self):\n        report = self.store.scan()\n        report.sort()\n        return report.summary()\n"
    out = run({"r": {"m.py": METHODS.format(n="A", own="") + METHODS.format(n="B", own=own_b)}})
    [g] = classes(out)
    assert g["tier"] == "near" and [m["qualname"] for m in g["members"]] == ["A", "B"]
    assert [[m["qualname"] for m in c["members"]] for c in g["children"]] == [["A.load", "B.load"], ["A.drop", "B.drop"]]
    assert g["differences"] == [{"member": "m2", "change": "added", "methods": ["audit"]}]
    assert [x["unit"] for x in out["groups"]] == ["class"]       # the method groups aren't repeated


def test_without_classes_the_method_groups_stay_top_level(run):
    out = run({"r": {"m.py": METHODS.format(n="A", own="") + METHODS.format(n="B", own="")}}, "--units", "functions")
    assert [g["unit"] for g in out["groups"]] == ["function", "function"]


def test_classes_sharing_two_fields_are_not_grouped(run):
    cls = "\nclass {n}:\n    def __init__(self, id, name, {x}):\n        self.id = id\n        self.name = name\n        self.{x} = {x}\n"
    assert classes(run({"r": {"m.py": cls.format(n="A", x="price") + cls.format(n="B", x="colour")}})) == []


def test_classes_with_only_their_own_methods_are_not_grouped(run):
    # same number of methods, none of them matching: not the same shape
    p = """
class P:
    def a(self):
        x = self.load()
        x.go()
        return x.done
    def b(self, n):
        total = sum(range(n))
        self.cache[n] = total
        return total
    def c(self):
        for item in self.items:
            item.close()
        self.items.clear()
"""
    q = """
class Q:
    def a(self, path):
        with open(path) as fh:
            data = fh.read()
        return data.splitlines()
    def b(self):
        self.lock.acquire()
        self.counter += 1
        self.lock.release()
    def c(self, key, value):
        if key in self.seen:
            raise ValueError(key)
        self.seen[key] = value
"""
    assert classes(run({"r": {"m.py": p + q}})) == []
