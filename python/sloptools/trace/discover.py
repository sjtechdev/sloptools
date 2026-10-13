"""What module name each file has, as code elsewhere would import it."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class Module:
    rel: str            # file path relative to the scanned root
    name: str           # dotted module name, as code elsewhere would import it
    import_root: str    # directory that would sit on sys.path for this module
    is_package: bool    # an __init__.py


class ModuleIndex:
    """Maps files to module names and back.

    A file's module name is its path relative to its *import root*: the
    nearest ancestor directory that is not itself a package (has no
    __init__.py). So src/pkg/mod.py is `pkg.mod` with import root `src`, and
    a loose script dir's files are named relative to that dir. Several
    import roots can coexist (src/ layout, scripts/, a monorepo of packages),
    and two roots may even define the same module name -- lookups prefer the
    importer's own root and refuse to guess between others.
    """

    def __init__(self, rels: list[str], root_name: str = ""):
        paths = [PurePosixPath(r) for r in rels]
        package_dirs = {p.parent for p in paths if p.name == "__init__.py"}
        # If the scanned root is itself a package, name its modules as the
        # package would be imported: <root_name>.mod, not bare `mod`.
        self._prefix = root_name if PurePosixPath(".") in package_dirs and root_name else ""
        self.by_rel: dict[str, Module] = {}
        self.by_name: dict[str, list[Module]] = {}
        for p in paths:
            m = self._make(p, package_dirs)
            self.by_rel[m.rel] = m
            self.by_name.setdefault(m.name, []).append(m)
        for ms in self.by_name.values():
            ms.sort(key=lambda m: m.rel)

    def _make(self, p: PurePosixPath, package_dirs: set[PurePosixPath]) -> Module:
        root = p.parent
        # Climb through packages. A directory without __init__.py directly
        # inside a package is an implicit namespace subpackage
        # (flask/sansio/), so it's climbed through too.
        while root != root.parent and (root in package_dirs or root.parent in package_dirs):
            root = root.parent
        parts = list(p.relative_to(root).with_suffix("").parts)
        if root in package_dirs and self._prefix:   # the scanned root is itself a package
            parts.insert(0, self._prefix)
        is_package = p.name == "__init__.py"
        if is_package:
            parts.pop()
        return Module(rel=p.as_posix(), name=".".join(parts),
                      import_root=root.as_posix(), is_package=is_package)

    def lookup(self, name: str, importer: Module, same_root_only: bool = False) -> Module | None:
        candidates = self.by_name.get(name, [])
        same_root = [m for m in candidates if m.import_root == importer.import_root]
        if same_root:
            return same_root[0]
        if same_root_only or len(candidates) != 1:
            return None     # absent, or ambiguous between other roots: don't guess
        return candidates[0]
