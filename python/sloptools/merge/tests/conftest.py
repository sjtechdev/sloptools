from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from sloptools.merge.cli import main


@pytest.fixture
def make_roots(tmp_path):
    """{root name: {relative path: source}} -> list of root dirs."""
    def _make(roots: dict[str, dict[str, str]]) -> list[Path]:
        out = []
        for name, files in roots.items():
            root = tmp_path / name
            root.mkdir(parents=True)
            for rel, src in files.items():
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(textwrap.dedent(src))
            out.append(root)
        return out
    return _make


@pytest.fixture
def run(make_roots, capsys):
    """Run slopmerge --json over the given roots and return the parsed output."""
    def _run(roots: dict[str, dict[str, str]], *args: str) -> dict:
        paths = [str(p) for p in make_roots(roots)]
        assert main(paths + ["--json", *args]) == 0
        return json.loads(capsys.readouterr().out)
    return _run
