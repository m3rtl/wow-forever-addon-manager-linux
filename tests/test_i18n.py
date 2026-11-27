"""Uebersetzungen: Aufrufe von _/N_/ngettext im Code gegen assets/locale/en.po pruefen (nur Standardbibliothek)."""
import ast
import re
import unittest

from helpers import ROOT  # noqa: F401  (legt das Projekt in sys.path)

import wfa_i18n

PO_FILE = ROOT / "assets" / "locale" / "en.po"
# Dateien, deren Texte noch nicht in en.po stehen; der spaetere Schritt leert die Menge.
PENDING = {"wfa_gui.py", "wfa_cli.py", "wfa_expert.py", "wow-forever-addon-manager.py"}
FUNCS = ("_", "N_", "ngettext")
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


def source_files():
    files = sorted(p for p in ROOT.glob("wfa_*.py") if p.name != "wfa_i18n.py")
    return files + [ROOT / "wow-forever-addon-manager.py"]


def _is_lit(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


class _Collector(ast.NodeVisitor):
    def __init__(self, fname):
        self.fname = fname
        self.depth = 0           # Verschachtelung in Funktionen/Lambdas (Klassenkoerper laufen beim Import)
        self.calls = []          # (datei, zeile, funktion, [args], in_funktion)

    def _enter(self, node):
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    visit_FunctionDef = visit_AsyncFunctionDef = visit_Lambda = _enter

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in FUNCS:
            self.calls.append((self.fname, node.lineno, node.func.id, node.args, self.depth > 0))
        self.generic_visit(node)


def collect():
    """-> (Fehlerliste, [(datei, zeile, msgid, plural|None)])."""
    errors, found = [], []
    for path in source_files():
        coll = _Collector(path.name)
        coll.visit(ast.parse(path.read_text(encoding="utf-8"), str(path)))
        for fname, line, func, args, in_func in coll.calls:
            where = f"{fname}:{line}"
            if func in ("_", "ngettext") and not in_func:
                errors.append(f"{where}: {func}() auf Modulebene (laeuft vor setup())")
            if func == "ngettext":
                if len(args) < 3 or not (_is_lit(args[0]) and _is_lit(args[1])):
                    errors.append(f"{where}: ngettext braucht zwei String-Literale und n")
                    continue
                found.append((fname, line, args[0].value, args[1].value))
                continue
            if not args:
                errors.append(f"{where}: {func}() ohne Argument")
            elif _is_lit(args[0]):
                found.append((fname, line, args[0].value, None))
            elif func == "_" and isinstance(args[0], (ast.Name, ast.Attribute, ast.Subscript, ast.Call)):
                continue         # uebersetzt eine mit N_ markierte Konstante (auch per Nachschlagen)
            else:
                errors.append(f"{where}: {func}() braucht ein String-Literal (kein f-String/Ausdruck)")
    return errors, found


def po_msgids(text):
    """Alle msgid-Schluessel der Datei in Reihenfolge (mit Duplikaten, ohne Kopfeintrag)."""
    ids, cur, in_id = [], None, False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("msgid ") or line.startswith("msgid\t"):
            if cur is not None:
                ids.append(cur)
            cur, in_id = wfa_i18n._unquote(line[5:].strip()), True
        elif line.startswith('"') and in_id and cur is not None:
            cur += wfa_i18n._unquote(line)
        else:
            in_id = False
    if cur is not None:
        ids.append(cur)
    return [i for i in ids if i]


def placeholders(s):
    return set(PLACEHOLDER.findall(s))


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PO_FILE.read_text(encoding="utf-8")
        cls.catalog = wfa_i18n.parse_po(cls.text)
        cls.errors, cls.found = collect()

    def test_calls_are_wellformed(self):
        self.assertEqual([], self.errors)

    def test_no_duplicate_msgids(self):
        ids = po_msgids(self.text)
        dups = sorted({i for i in ids if ids.count(i) > 1})
        self.assertEqual([], dups)

    def test_header(self):
        self.assertIn('"Content-Type: text/plain; charset=UTF-8\\n"', self.text)
        self.assertIn('"Language: en\\n"', self.text)
        self.assertIn('"Plural-Forms: nplurals=2; plural=(n != 1);\\n"', self.text)

    def test_every_msgid_translated(self):
        missing = [f"{f}:{ln}: {mid!r}" for f, ln, mid, _pl in self.found
                   if f not in PENDING and mid not in self.catalog]
        self.assertEqual([], missing)

    def test_placeholders_match(self):
        bad = []
        for f, ln, mid, plural in self.found:
            tr = self.catalog.get(mid)
            if tr is None:
                continue
            if plural is None:
                if not isinstance(tr, str):
                    bad.append(f"{f}:{ln}: {mid!r}: Mehrzahl-Eintrag fuer einfachen Text")
                elif placeholders(mid) != placeholders(tr):
                    bad.append(f"{f}:{ln}: {mid!r}: {sorted(placeholders(mid))} != {sorted(placeholders(tr))}")
            else:
                if not isinstance(tr, tuple):
                    bad.append(f"{f}:{ln}: {mid!r}: Mehrzahl-Eintrag fehlt")
                    continue
                want = placeholders(plural)
                if placeholders(tr[1]) != want or not placeholders(tr[0]) <= want:
                    bad.append(f"{f}:{ln}: {mid!r}: Platzhalter der Mehrzahl weichen ab")
        self.assertEqual([], bad)


class RoundtripTest(unittest.TestCase):
    def tearDown(self):
        wfa_i18n.setup("de")

    def test_setup_en(self):
        self.assertEqual("en", wfa_i18n.setup("en"))
        self.assertEqual("en", wfa_i18n.current())
        self.assertEqual("Cancel", wfa_i18n._("Abbrechen"))
        self.assertEqual("Unbekannt-xyz", wfa_i18n._("Unbekannt-xyz"))      # ohne Eintrag: Original
        self.assertEqual("1 result", wfa_i18n.ngettext("1 Treffer", "{n} Treffer", 1))
        self.assertEqual("{n} results", wfa_i18n.ngettext("1 Treffer", "{n} Treffer", 3))
        self.assertEqual("1 result", wfa_i18n.ngettext("1 Treffer", "{n} Treffer", 1).format(n=1))

    def test_setup_de(self):
        wfa_i18n.setup("en")
        self.assertEqual("de", wfa_i18n.setup("de"))
        self.assertEqual("Abbrechen", wfa_i18n._("Abbrechen"))
        self.assertEqual("1 Treffer", wfa_i18n.ngettext("1 Treffer", "{n} Treffer", 1))
        self.assertEqual("{n} Treffer", wfa_i18n.ngettext("1 Treffer", "{n} Treffer", 2))

    def test_n_marker_is_identity(self):
        self.assertEqual("Abbrechen", wfa_i18n.N_("Abbrechen"))

    def test_detect(self):
        self.assertEqual("de", wfa_i18n.detect({"LANG": "de_DE.UTF-8"}))
        self.assertEqual("de", wfa_i18n.detect({"LANGUAGE": "de:en", "LANG": "en_US.UTF-8"}))
        self.assertEqual("en", wfa_i18n.detect({"LANG": "en_US.UTF-8"}))
        self.assertEqual("en", wfa_i18n.detect({"LANG": "C"}))
        self.assertEqual("en", wfa_i18n.detect({"LANG": "C.UTF-8"}))
        self.assertEqual("en", wfa_i18n.detect({}))


if __name__ == "__main__":
    unittest.main()
