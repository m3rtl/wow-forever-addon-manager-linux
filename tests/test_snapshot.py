import io
import tarfile
import tempfile
import unittest
from pathlib import Path

import wfa_snapshot as sn


def _w(p, text="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _tree(d):
    return {str(p.relative_to(d)): (p.read_text() if p.is_file() else None) for p in sorted(d.rglob("*"))}


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        r = Path(self._t.name)
        self.addons, self.wtf, self.root = r / "Interface" / "AddOns", r / "WTF", r / "snaps"
        _w(self.addons / "A" / "A.toc", "1")
        _w(self.addons / "B" / "B.toc", "1")
        _w(self.wtf / "Account" / "X" / "SavedVariables" / "A.lua", "v1")
        _w(self.wtf / "config.wtf", "keep")

    def test_roundtrip_safety_and_list(self):
        s = sn.create(self.addons, self.wtf, self.root, label="L", client="1.60", keep=3)
        self.assertEqual((s.addons, s.label, s.client), (["A", "B"], "L", "1.60"))
        self.assertTrue(s.manager_version)
        before_a, before_w = _tree(self.addons), _tree(self.wtf / "Account")
        _w(self.addons / "A" / "A.toc", "2")
        _w(self.addons / "C" / "C.toc")
        _w(self.wtf / "Account" / "X" / "SavedVariables" / "A.lua", "v2")
        safety = sn.restore(s, self.addons, self.wtf, self.root)
        self.assertEqual(safety.label, "Vor Wiederherstellung")
        self.assertEqual(_tree(self.addons), before_a)
        self.assertEqual(_tree(self.wtf / "Account"), before_w)
        self.assertEqual((self.wtf / "config.wtf").read_text(), "keep")
        self.assertFalse(list(self.addons.parent.glob("*.wfa-*")))
        # Sicherheits-Satz enthaelt den geaenderten Stand
        sn.restore(safety, self.addons, self.wtf, self.root)
        self.assertTrue((self.addons / "C" / "C.toc").exists())
        ids = [x.id for x in sn.list_snapshots(self.root)]
        self.assertEqual(ids, sorted(ids, reverse=True))
        sn.delete(safety)
        self.assertNotIn(safety.id, [x.id for x in sn.list_snapshots(self.root)])

    def test_rotation_protects_snap(self):
        old = sn.create(self.addons, self.wtf, self.root, keep=2)
        for _ in range(3):
            sn.create(self.addons, self.wtf, self.root, keep=2)
        self.assertEqual(len(sn.list_snapshots(self.root)), 2)
        self.assertNotIn(old.id, [x.id for x in sn.list_snapshots(self.root)])
        # alter Satz wird bei Wiederherstellung durch Rotation nicht geloescht
        s1 = sn.create(self.addons, self.wtf, self.root, keep=2)
        sn.create(self.addons, self.wtf, self.root, keep=2)
        sn.restore(s1, self.addons, self.wtf, self.root, keep=1)
        self.assertIn(s1.id, [x.id for x in sn.list_snapshots(self.root)])

    def test_broken_skipped(self):
        sn.create(self.addons, self.wtf, self.root)
        (self.root / "20200101-000000").mkdir()
        _w(self.root / "20200101-000001" / "meta.json", "{kaputt")
        self.assertEqual(len(sn.list_snapshots(self.root)), 1)

    def _evil(self, make):
        s = sn.create(self.addons, self.wtf, self.root)
        with tarfile.open(s.path / "addons.tar.gz", "w:gz") as tf:
            make(tf)
        before = _tree(self.addons)
        with self.assertRaises(ValueError):
            sn.restore(s, self.addons, self.wtf, self.root)
        self.assertEqual(_tree(self.addons), before)

    def test_malicious_tar(self):
        def reg(name):
            def f(tf):
                ti = tarfile.TarInfo(name)
                ti.size = 1
                tf.addfile(ti, io.BytesIO(b"x"))
            return f

        def link(tf):
            ti = tarfile.TarInfo("lnk")
            ti.type = tarfile.SYMTYPE
            ti.linkname = "/etc"
            tf.addfile(ti)
        self._evil(reg("../x"))
        self._evil(reg("/abs/x"))
        self._evil(link)


if __name__ == "__main__":
    unittest.main()
