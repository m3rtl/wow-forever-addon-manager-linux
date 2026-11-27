import tempfile
import unittest
from pathlib import Path

import wfa_cleanup as cl


def _w(p, text="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        r = Path(self._t.name)
        self.addons, self.wtf, self.trash = r / "AddOns", r / "WTF", r / "trash"
        _w(self.addons / "Good" / "Good.toc")
        _w(self.addons / "Outer" / "Outer" / "Outer.toc")
        _w(self.addons / "Outer" / "Outer" / "main.lua", "code")
        _w(self.addons / "Junk" / "readme.txt", "abc")
        acc = self.wtf / "Account" / "ACC"
        _w(acc / "SavedVariables" / "good.lua")             # case-insensitive bekannt
        _w(acc / "SavedVariables" / "Gone.lua")
        _w(acc / "SavedVariables" / "Gone.lua.bak")
        _w(acc / "SavedVariables" / "Blizzard_Foo.lua")
        _w(acc / "R" / "C" / "SavedVariables" / "Weg.lua")
        self.r = r

    def kinds(self, fs):
        return sorted((f.kind, f.detail) for f in fs)

    def test_scan(self):
        got = self.kinds(cl.scan(self.addons, self.wtf))
        self.assertEqual(got, [("nested", "Outer"), ("no_toc", "Junk"), ("orphan_sv", "Gone"), ("orphan_sv", "Gone"),
                               ("orphan_sv", "Weg")])
        self.assertEqual(len([f for f in cl.scan(self.addons, None) if f.kind == "orphan_sv"]), 0)
        self.assertEqual(len([f for f in cl.scan(self.addons, self.r / "x") if f.kind == "orphan_sv"]), 0)

    def test_apply_restore_conflict_rotation(self):
        fs = cl.scan(self.addons, self.wtf)
        res = cl.apply(fs, self.addons, self.trash)
        self.assertTrue(all(ok for _f, ok, _m in res))
        self.assertTrue((self.addons / "Outer" / "Outer.toc").exists())      # innerer ersetzt aeusseren
        self.assertFalse((self.addons / "Junk").exists())
        sets = cl.list_sets(self.trash)
        self.assertEqual(len(sets), 1)
        self.assertEqual(sets[0][2], len(fs))
        # Konflikt: Ziel neu angelegt
        _w(self.addons / "Junk" / "neu.txt")
        errs = cl.restore_set(sets[0][0])
        self.assertEqual(len(errs), 2)          # Junk + Outer (existiert als Ersatz)
        self.assertTrue((self.addons / "Junk" / "neu.txt").exists())
        self.assertFalse((self.addons / "Junk" / "readme.txt").exists())
        self.assertTrue((self.wtf / "Account" / "ACC" / "SavedVariables" / "Gone.lua").exists())
        self.assertEqual(cl.list_sets(self.trash)[0][2], 2)      # Rest bleibt im Satz

    def test_rotation_and_missing(self):
        for i in range(4):
            (self.trash / "2020010{}-000000".format(i + 1)).mkdir(parents=True)
        _w(self.addons / "J2" / "a.txt")
        f = cl.Finding("no_toc", self.addons / "J2", 1, "J2")
        cl.apply([f], self.addons, self.trash, keep=2)
        names = [p.name for p, _c, _n in cl.list_sets(self.trash)]
        self.assertEqual(len(names), 2)
        self.assertEqual(names[1], "20200104-000000")
        bad = cl.apply([cl.Finding("no_toc", self.addons / "nix", 0, "nix")], self.addons, self.trash)
        self.assertFalse(bad[0][1])

    def test_disk_usage(self):
        (self.r / "lnk").symlink_to(self.addons)
        u = cl.disk_usage({"a": self.addons / "Junk", "n": self.r / "none", "l": self.r / "lnk"})
        self.assertEqual(u["a"], 3)
        self.assertEqual(u["n"], 0)
        self.assertLess(u["l"], 1000)


if __name__ == "__main__":
    unittest.main()
