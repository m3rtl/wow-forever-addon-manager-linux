"""Kein lokaler Name `_` in Funktionen, die _() aufrufen (sonst TypeError/UnboundLocalError zur Laufzeit)."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted(ROOT.glob("wfa_*.py")) + [ROOT / "wow-forever-addon-manager.py"]


def _binds_underscore(fn):
    a = fn.args
    params = a.posonlyargs + a.args + a.kwonlyargs + [x for x in (a.vararg, a.kwarg) if x]
    if any(p.arg == "_" for p in params):
        return True
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and node.id == "_" and isinstance(node.ctx, ast.Store):
            return True
    return False


def _calls_underscore(fn):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_" for n in ast.walk(fn))


class ShadowTest(unittest.TestCase):
    def test_no_shadowed_gettext(self):
        bad = []
        for path in FILES:
            for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and not isinstance(fn, ast.Lambda):
                    if _binds_underscore(fn) and _calls_underscore(fn):
                        bad.append(f"{path.name}:{fn.lineno} {fn.name}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
