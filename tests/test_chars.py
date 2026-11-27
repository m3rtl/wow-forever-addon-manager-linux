import tempfile
import unittest
from pathlib import Path

import wfa_chars as ch


def _w(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode())


class CharsTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.root = Path(self._t.name)
        self.wtf = self.root / "WTF"
        acc = self.wtf / "Account" / "123456#1"
        _w(acc / "config-cache.wtf", "x")
        _w(acc / "SavedVariables" / "A.lua", "x")
        _w(acc / "Realm" / "Zed" / "AddOns.txt", "A: enabled\r\nB: disabled\r\n")
        _w(acc / "Realm" / "Amy" / "SavedVariables" / "A.lua", "x")
        _w(acc / "1234" / "Bob" / "layout.wtf", "x")
        (acc / "Realm" / "Leer").mkdir()

    def test_list(self):
        got = [(c.account, c.realm, c.name) for c in ch.list_characters(self.wtf)]
        self.assertEqual(got, [("123456#1", "1234", "Bob"), ("123456#1", "Realm", "Amy"), ("123456#1", "Realm", "Zed")])
        self.assertEqual(ch.list_characters(self.root / "none"), [])

    def _zed(self):
        return next(c for c in ch.list_characters(self.wtf) if c.name == "Zed")

    def test_read_and_default(self):
        c = self._zed()
        st = ch.read_states(c)
        self.assertEqual(st, {"A": True, "B": False})
        self.assertFalse(ch.is_enabled(st, "b"))
        self.assertTrue(ch.is_enabled(st, "Neu"))
        amy = next(x for x in ch.list_characters(self.wtf) if x.name == "Amy")
        self.assertEqual(ch.read_states(amy), {})

    def test_write_keeps_order_unknown_crlf_and_appends(self):
        c = self._zed()
        f = c.path / "AddOns.txt"
        _w(f, "## komisch\r\nA: enabled\r\nb: disabled\r\nC: enabled")
        bk = self.root / "bk"
        ch.write_states(c, {"B": True, "A": False, "Neu": False}, bk)
        self.assertEqual(f.read_bytes().decode(), "## komisch\r\nA: disabled\r\nb: enabled\r\nC: enabled\r\nNeu: disabled\r\n")
        old = (bk / "123456#1" / "Realm" / "Zed" / "AddOns.txt").read_bytes().decode()
        self.assertTrue(old.startswith("## komisch") and "A: enabled" in old)

    def test_write_lf_and_create(self):
        c = self._zed()
        _w(c.path / "AddOns.txt", "A: enabled\nB: disabled\n")
        ch.write_states(c, {"X": True})
        self.assertEqual((c.path / "AddOns.txt").read_bytes().decode(), "A: enabled\nB: disabled\nX: enabled\n")
        amy = next(x for x in ch.list_characters(self.wtf) if x.name == "Amy")
        ch.write_states_all([amy], {"A": False}, self.root / "bk")
        self.assertEqual(ch.read_states(amy), {"A": False})
        self.assertFalse((self.root / "bk").exists())   # nichts zu sichern


if __name__ == "__main__":
    unittest.main()
