import unittest

import wfa_core as core
from helpers import OfflineCase, build_info, make_addon, make_wow, write


class TocTests(OfflineCase):
    def test_parse_toc(self):
        p = write(self.tmp / "A.toc", "﻿## Interface: 16001, 11500\n##Title : Hallo\n## Title: zweiter\n#kein\n")
        meta = core.parse_toc(p)
        self.assertEqual(meta["interface"], "16001, 11500")
        self.assertEqual(meta["title"], "Hallo")   # erster Eintrag gewinnt
        self.assertEqual(core.parse_toc(self.tmp / "fehlt.toc"), {})

    def test_interfaces(self):
        self.assertEqual(core.interfaces({"interface": "16001, 11500"}), [16001, 11500])
        self.assertEqual(core.interfaces({}), [])

    def test_clean_title(self):
        self.assertEqual(core.clean_title("|cff00ff00Name|r"), "Name")

    def test_toc_files_and_forever_toc(self):
        d = make_addon(self.tmp, "Foo", interface=16001, version="2.0")
        self.assertEqual(core.toc_files(d)["foo.toc"], "Foo.toc")
        self.assertEqual(core.toc_files(self.tmp / "nix"), {})
        st, ver, toc = core.forever_toc(d)
        self.assertEqual((st, ver, toc.name), ("ok", "2.0", "Foo.toc"))

    def test_forever_toc_status(self):
        self.assertEqual(core.forever_toc(make_addon(self.tmp, "Alt", interface=16000), 16001)[0], "veraltet")
        self.assertEqual(core.forever_toc(make_addon(self.tmp, "Classic", interface=11500))[0], "nein")
        self.assertEqual(core.forever_toc(self.tmp / "Leer"), ("nein", None, None))

    def test_forever_toc_prefers_forever_file_and_falls_back_for_version(self):
        d = make_addon(self.tmp, "Bar", interface=11500, version="1.5")
        write(d / "Bar_Forever.toc", "## Interface: 16001\n## Version: @project-version@\n")
        st, ver, toc = core.forever_toc(d)
        self.assertEqual((st, ver, toc.name), ("ok", "1.5", "Bar_Forever.toc"))

    def test_toc_dependencies(self):
        d = make_addon(self.tmp, "Dep", extra_toc="## Dependencies: LibA, LibB\n## RequiredDeps: LibA, Zed")
        self.assertEqual(core.toc_dependency_names(d), ["LibA", "LibB", "Zed"])
        self.assertEqual(core.toc_dependencies(d), {"liba", "libb", "zed"})
        self.assertEqual(core.toc_dependencies(self.tmp / "nix"), set())

    def test_toc_meta_fallback(self):
        d = write(self.tmp / "X" / "X_Mainline.toc", "## Title: nur Mainline\n").parent
        self.assertEqual(core.toc_meta(d)["title"], "nur Mainline")


class ClientTests(OfflineCase):
    def test_client_version_from_build_info(self):
        addons = make_wow(self.tmp, build_info(("wow_classic", "1.14.4.1"), ("wowf", "1.60.1.12345")))
        self.assertEqual(core.client_version(addons), "1.60.1")   # Forever-Version bevorzugt
        self.assertEqual(core.client_interface(addons), 16001)

    def test_flavor_filter(self):
        addons = make_wow(self.tmp, build_info(("wowf", "1.60.2.1"), ("wow", "1.61.0.1")),
                          flavor="x\nwow\n")
        self.assertEqual(core.client_version(addons), "1.61.0")

    def test_without_build_info_votes_by_addons(self):
        addons = make_wow(self.tmp)
        for n in ("A", "B"):
            make_addon(addons, n, interface=16003)
        make_addon(addons, "C", interface=16009)   # einzelner Ausreisser
        self.assertIsNone(core.client_version(addons))
        self.assertEqual(core.client_interface(addons), 16003)

    def test_default_without_anything(self):
        self.assertEqual(core.client_interface(make_wow(self.tmp)), core.DEFAULT_CLIENT)

    def test_version_interface(self):
        self.assertEqual(core.version_interface("1.60.1"), 16001)
        self.assertIsNone(core.version_interface("x"))


if __name__ == "__main__":
    unittest.main()
