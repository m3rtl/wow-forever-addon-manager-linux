"""Keine Methode darf in derselben Klasse ein zweites Mal definiert werden (die zweite überschreibt still die erste)."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class NoShadowedMethodsTests(unittest.TestCase):
    def test_no_duplicate_defs(self):
        found = []
        for f in sorted(ROOT.glob("wfa_*.py")) + [ROOT / "wow-forever-addon-manager.py"]:
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Module, ast.ClassDef)):
                    continue
                seen = {}
                for n in node.body:
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        # Property-Setter u. ä. tragen Dekoratoren und dürfen den Namen wiederholen
                        if n.name in seen and not n.decorator_list:
                            found.append("{}:{} {} (zuerst Zeile {})".format(f.name, n.lineno, n.name, seen[n.name]))
                        seen[n.name] = n.lineno
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
