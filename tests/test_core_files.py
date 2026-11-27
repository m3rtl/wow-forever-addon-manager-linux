import os
import unittest

import wfa_core as core
from helpers import OfflineCase, make_addon, make_wow, make_zip, write


class HashTests(OfflineCase):
    def test_murmur2_stable(self):
        # Selbstkonsistenz: leere Daten mit Seed 1 -> Mischung ohne Eingabe, Ergebnis deterministisch
        self.assertEqual(core.murmur2(b""), core.murmur2(b""))
        self.assertNotEqual(core.murmur2(b"abcd"), core.murmur2(b"abce"))
        self.assertNotEqual(core.murmur2(b"abc"), core.murmur2(b"abcd"))   # Rest-Zweige 3 / 0
        for n in range(8):
            self.assertLess(core.murmur2(b"x" * n), 2 ** 32)
        self.assertNotEqual(core.murmur2(b"abc", 1), core.murmur2(b"abc", 2))

    def test_fingerprint_deterministic_and_content_sensitive(self):
        d = make_addon(self.tmp, "Fp", files={"Fp.xml": '<Script file="x.lua"/>'})
        write(d / "Fp.toc", "## Interface: 16001\nFp.lua\nFp.xml\n")
        write(d / "x.lua", "a = 1")
        fp = core.fingerprint(d)
        self.assertEqual(fp, core.fingerprint(d))
        write(d / "x.lua", "a = 2")
        self.assertNotEqual(fp, core.fingerprint(d))

    def test_fingerprint_ignores_whitespace_and_unlisted_files(self):
        d = make_addon(self.tmp, "Ws")
        fp = core.fingerprint(d)
        write(d / "Ws.lua", "--   Ws\r\n")      # nur Leerraum geaendert
        write(d / "unlisted.lua", "irgendwas")
        self.assertEqual(fp, core.fingerprint(d))

    def test_fingerprint_custom_hasher_and_case_insensitive_include(self):
        d = make_addon(self.tmp, "Ci")
        write(d / "Ci.toc", "## Interface: 16001\nSUB\\File.LUA\n")
        write(d / "sub" / "file.lua", "x")
        seen = []
        core.fingerprint(d, hasher=lambda p: seen.append(os.path.basename(p)) or 1)
        self.assertEqual(sorted(seen), ["Ci.toc", "file.lua"])


class ZipTests(OfflineCase):
    def test_safe_extract_normal(self):
        z = make_zip(self.tmp / "a.zip", {"Foo/Foo.toc": "x", "Foo/sub/a.lua": "y", "Foo/leer/": "",
                                          "__MACOSX/Foo/._x": "m"})
        dest = self.tmp / "out"
        dest.mkdir()
        core.safe_extract(z, dest)
        self.assertTrue((dest / "Foo" / "sub" / "a.lua").is_file())
        self.assertTrue((dest / "Foo" / "leer").is_dir())
        self.assertFalse((dest / "__MACOSX").exists())

    def test_safe_extract_rejects_unsafe(self):
        for bad in ("../evil.txt", "Foo/../../evil.txt", "/abs.txt", "C:/x.txt", "..\\evil.txt", "Foo\\..\\..\\e.txt"):
            with self.subTest(bad=bad):
                z = make_zip(self.tmp / "b.zip", {bad: "x"})
                dest = self.tmp / "o"
                dest.mkdir(exist_ok=True)
                with self.assertRaises(ValueError):
                    core.safe_extract(z, dest)
        self.assertFalse((self.tmp / "evil.txt").exists())

    def test_safe_extract_backslash_paths_are_normalised(self):
        z = make_zip(self.tmp / "c.zip", {"Foo\\Foo.toc": "x"})
        dest = self.tmp / "o2"
        dest.mkdir()
        core.safe_extract(z, dest)
        self.assertTrue((dest / "Foo" / "Foo.toc").is_file())

    def test_safe_extract_rejects_symlink(self):
        import zipfile
        p = self.tmp / "s.zip"
        with zipfile.ZipFile(p, "w") as zf:
            i = zipfile.ZipInfo("Foo/link")
            i.external_attr = (0o120777 << 16)
            zf.writestr(i, "/etc/passwd")
        dest = self.tmp / "o3"
        dest.mkdir()
        with self.assertRaises(ValueError):
            core.safe_extract(p, dest)

    def test_check_zip(self):
        core.check_zip(make_zip(self.tmp / "ok.zip", {"a": "b"}))
        write(self.tmp / "no.zip", "kein zip")
        with self.assertRaises(core.ApiError) as cm:
            core.check_zip(self.tmp / "no.zip")
        self.assertEqual(cm.exception.kind, "download")

    def test_check_zip_corrupt(self):
        z = make_zip(self.tmp / "bad.zip", {"a": "inhalt" * 100})
        data = bytearray(z.read_bytes())
        data[40] ^= 0xFF   # Nutzdaten kippen -> CRC-Fehler
        z.write_bytes(bytes(data))
        with self.assertRaises(core.ApiError) as cm:
            core.check_zip(z)
        self.assertEqual(cm.exception.kind, "corrupt")


class DirTests(OfflineCase):
    def test_is_addon_dir_and_find(self):
        root = self.tmp / "root"
        make_addon(root, "Alpha")
        make_addon(root / "wrapper", "Beta")
        write(root / "Gamma" / "Other.toc", "## Interface: 1\n")   # TOC passt nicht zum Ordnernamen
        write(root / "Delta" / "Delta_Forever.toc", "## Interface: 16001\n")
        write(root / "__MACOSX" / "Eps" / "Eps.toc", "")
        self.assertTrue(core.is_addon_dir(root / "Alpha"))
        self.assertFalse(core.is_addon_dir(root / "Gamma"))
        found = {p.name: d for p, d in core.find_addon_dirs(root)}
        self.assertEqual(found, {"Alpha": 0, "Beta": 1, "Delta": 0})


class AddonsDirTests(OfflineCase):
    def test_normalize(self):
        addons = make_wow(self.tmp)
        wow = addons.parent.parent.parent
        for p in (wow, wow / "_forever_", wow / "_forever_" / "Interface", addons):
            with self.subTest(p=p):
                self.assertEqual(core.normalize_addons_dir(p), addons)

    def test_normalize_with_extra_interface_and_case(self):
        addons = make_wow(self.tmp)
        wow = addons.parent.parent.parent
        (wow / "Interface").mkdir()
        self.assertEqual(core.normalize_addons_dir(wow), addons)
        other = self.tmp / "irgendwo"
        self.assertEqual(core.normalize_addons_dir(other), other)

    def test_validate(self):
        addons = make_wow(self.tmp)
        self.assertEqual(core.validate_addons_dir(addons), (True, ""))
        self.assertEqual(core.validate_addons_dir(addons.parent.parent.parent), (True, ""))
        ok, hint = core.validate_addons_dir(self.tmp / "nix")
        self.assertFalse(ok)
        self.assertIn("existiert nicht", hint)

    def test_validate_warnings_and_creatable(self):
        plain = self.tmp / "Foo" / "AddOns"
        plain.mkdir(parents=True)
        ok, hint = core.validate_addons_dir(plain)
        self.assertTrue(ok)
        self.assertIn("_forever_", hint)
        fr = self.tmp / "W" / "_forever_"
        fr.mkdir(parents=True)
        ok, hint = core.validate_addons_dir(fr)   # AddOns fehlt noch
        self.assertTrue(ok)
        self.assertIn("angelegt", hint)

    def test_validate_not_addons(self):
        d = self.tmp / "Interface" / "Anderes"
        d.mkdir(parents=True)
        self.assertEqual(core.validate_addons_dir(d), (False, "Das ist kein AddOns-Ordner."))


if __name__ == "__main__":
    unittest.main()
