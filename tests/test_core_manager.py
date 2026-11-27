import unittest
from unittest import mock

import wfa_core as core
from helpers import OfflineCase, make_addon, make_wow, write


class ManagerCase(OfflineCase):
    def setUp(self):
        super().setUp()
        self.addons = make_wow(self.tmp)
        self.wow = self.addons.parent.parent.parent
        self.mgr = core.Manager(addons_dir=self.addons)
        # kein pgrep im Test
        p = mock.patch.object(self.mgr, "wow_running", return_value=False)
        p.start()
        self.addCleanup(p.stop)


class ScanTests(ManagerCase):
    def test_needs_setup(self):
        self.assertTrue(core.Manager().needs_setup())
        self.assertFalse(self.mgr.needs_setup())
        with self.assertRaises(core.ApiError):
            core.Manager().scan()

    def test_scan_finds_folders(self):
        make_addon(self.addons, "Alpha")
        make_addon(self.addons, "Beta")
        (self.addons / "KeinAddon").mkdir()
        write(self.addons / "Datei.txt", "x")
        pkgs = self.mgr.scan()
        self.assertEqual(sorted(f for p in pkgs for f in p.folders), ["Alpha", "Beta"])
        self.assertEqual(self.mgr._addon_folders(), ["Alpha", "Beta"])

    def test_set_addons_dir_persists(self):
        m = core.Manager()
        m.set_addons_dir(self.wow)
        self.assertEqual(m.addons_dir, self.addons)
        self.assertEqual(core.Manager().addons_dir, self.addons)
        with self.assertRaises(ValueError):
            m.set_addons_dir(self.tmp / "nix")

    def test_client_read_from_build_info(self):
        write(self.wow / ".build.info", "Branch!STRING:0|Product!STRING:0|Version!STRING:0\neu|wowf|1.60.3.1\n")
        m = core.Manager(addons_dir=self.addons)
        self.assertEqual((m.client_version, m.client_interface), ("1.60.3", 16003))


class UninstallRestoreTests(ManagerCase):
    def test_uninstall_moves_to_backup_and_restore(self):
        make_addon(self.addons, "Alpha", files={"data.txt": "wichtig"})
        make_addon(self.addons, "Beta")
        pkg = next(p for p in self.mgr.scan() if p.folders == ["Alpha"])
        plan = self.mgr.plan_uninstall(pkg)
        self.assertEqual(plan.folders, ["Alpha"])
        res = self.mgr.uninstall([plan])
        self.assertTrue(res[0].ok, res[0].message)
        self.assertFalse((self.addons / "Alpha").exists())
        self.assertTrue((self.addons / "Beta").exists())
        sets = self.mgr.list_backups()
        self.assertEqual(len(sets), 1)
        self.assertEqual(sets[0].folders, ["Alpha"])
        self.assertEqual(sets[0].name, res[0].backup_set)

        r = self.mgr.restore(sets[0])
        self.assertTrue(r.ok, r.message)
        self.assertEqual((self.addons / "Alpha" / "data.txt").read_text(), "wichtig")
        self.assertEqual(self.mgr.list_backups(), [])
        kinds = [h["kind"] for h in self.mgr.read_history()]
        self.assertEqual(sorted(kinds), ["Deinstallation", "Wiederherstellung"])

    def test_uninstall_without_folders_and_empty_restore(self):
        res = self.mgr.uninstall([core.UninstallPlan("k", "K", [])])
        self.assertFalse(res[0].ok)
        self.assertEqual(self.mgr.list_backups(), [])
        gone = core.BackupSet("x", self.tmp / "gibt-es-nicht", 0, [])
        self.assertFalse(self.mgr.restore(gone).ok)

    def test_plan_uninstall_warns_about_dependents(self):
        make_addon(self.addons, "LibX")
        make_addon(self.addons, "User", extra_toc="## Dependencies: LibX")
        pkg = core.Package("k", "LibX", ["LibX", "Fehlt"])
        plan = self.mgr.plan_uninstall(pkg)
        self.assertEqual(plan.folders, ["LibX"])
        self.assertEqual(plan.dependents, {"User": ["LibX"]})
        self.assertEqual(len(plan.warnings), 2)

    def test_restore_only_selected(self):
        make_addon(self.addons, "A")
        make_addon(self.addons, "B")
        pkgs = self.mgr.scan()
        self.mgr.uninstall([self.mgr.plan_uninstall(p) for p in pkgs])
        bset = self.mgr.list_backups()[0]
        self.assertEqual(bset.folders, ["A", "B"])
        self.assertTrue(self.mgr.restore(bset, only=["B"]).ok)
        self.assertTrue((self.addons / "B").exists())
        self.assertFalse((self.addons / "A").exists())

    def test_backups_are_pruned(self):
        for i in range(core.KEEP_BACKUPS + 3):
            make_addon(self.addons, f"Ad{i}")
            self.mgr.uninstall([self.mgr.plan_uninstall(core.Package(f"k{i}", "n", [f"Ad{i}"]))])
        self.assertEqual(len(self.mgr.list_backups()), core.KEEP_BACKUPS)


class SavedVariablesTests(ManagerCase):
    def make_wtf(self):
        wtf = self.addons.parent.parent / "WTF"
        write(wtf / "Account" / "ACC" / "SavedVariables" / "Foo.lua", "Foo = 1")
        write(wtf / "Account" / "ACC" / "SavedVariables" / "Foo.lua.bak", "ignoriert")
        write(wtf / "Account" / "ACC" / "Realm" / "Char" / "SavedVariables" / "Bar.lua", "Bar = 1")
        write(wtf / "Config.wtf", "nicht dabei")
        return wtf

    def test_snapshot_and_restore(self):
        wtf = self.make_wtf()
        name = self.mgr.snapshot_sv()
        self.assertIsNotNone(name)
        sets = self.mgr.list_sv_backups()
        self.assertEqual((sets[0].name, sets[0].addons, sets[0].files), (name, ["Bar", "Foo"], 2))
        self.assertFalse((sets[0].path / "Config.wtf").exists())

        foo = wtf / "Account" / "ACC" / "SavedVariables" / "Foo.lua"
        foo.write_text("Foo = 99")
        (wtf / "Account" / "ACC" / "Realm" / "Char" / "SavedVariables" / "Bar.lua").write_text("Bar = 99")
        res = self.mgr.restore_sv(sets[0], addons=["foo"])
        self.assertTrue(res.ok, res.message)
        self.assertEqual(foo.read_text(), "Foo = 1")
        self.assertEqual((wtf / "Account" / "ACC" / "Realm" / "Char" / "SavedVariables" / "Bar.lua").read_text(), "Bar = 99")
        self.assertIsNotNone(res.sv_set)           # Stand vor dem Zurückschreiben gesichert
        self.assertIn("Einstellungen", [h["kind"] for h in self.mgr.read_history()])

    def test_restore_blocked_while_wow_runs(self):
        self.make_wtf()
        self.mgr.snapshot_sv()
        with mock.patch.object(self.mgr, "wow_running", return_value=True):
            res = self.mgr.restore_sv(self.mgr.list_sv_backups()[0])
        self.assertFalse(res.ok)
        self.assertIn("WoW läuft", res.message)

    def test_snapshot_without_wtf_or_files(self):
        logs = []
        self.mgr.log = logs.append
        self.assertIsNone(self.mgr.snapshot_sv())
        (self.addons.parent.parent / "WTF").mkdir()
        self.assertIsNone(self.mgr.snapshot_sv())
        self.assertEqual(self.mgr.list_sv_backups(), [])
        self.assertEqual(len(logs), 2)

    def test_case_insensitive_wtf_dirs(self):
        wtf = self.addons.parent.parent / "wtf"
        write(wtf / "account" / "ACC" / "savedvariables" / "Foo.lua", "1")
        self.assertEqual(self.mgr.wtf_dir(), wtf)
        self.assertIsNotNone(self.mgr.snapshot_sv())

    def test_sv_snapshots_are_pruned(self):
        self.make_wtf()
        for _ in range(core.KEEP_BACKUPS + 2):
            self.mgr.snapshot_sv()
        self.assertEqual(len(self.mgr.list_sv_backups()), core.KEEP_BACKUPS)


if __name__ == "__main__":
    unittest.main()
