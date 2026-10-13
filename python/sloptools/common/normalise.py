"""AST normalisation: erase what a copy-paste usually changes."""

from __future__ import annotations

import ast


class Normaliser(ast.NodeTransformer):
    """Erase local identifiers and literals so renamed copy-paste still
    matches -- but keep attribute names, and the name of a directly-called
    function, intact. Erasing those too made unrelated statements collide
    on shape alone (`results.append(x)` and `results.update(x)` both
    became `V.A(V)`); preserving them means a match now requires the same
    *operation*, not just the same syntactic silhouette.
    """

    def visit_Call(self, n: ast.Call) -> ast.Call:
        if not isinstance(n.func, ast.Name):
            n.func = self.visit(n.func)
        n.args = [self.visit(a) for a in n.args]
        n.keywords = [self.visit(k) for k in n.keywords]
        return n

    def visit_Name(self, n):
        return ast.copy_location(ast.Name(id="V", ctx=n.ctx), n)

    def visit_arg(self, n):
        n.arg, n.annotation = "V", None
        return n

    def visit_Constant(self, n):
        return ast.copy_location(ast.Constant(value="C"), n)
