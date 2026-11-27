import json
import os
from unittest import mock

import wfa_chars
import wfa_cleanup
import wfa_core as core
import wfa_snapshot
from helpers import OfflineCase, make_addon, make_wow, make_zip, write


class InstCase(OfflineCase):
    def setUp(self):
        super().setUp()
        self.a = make_wow(self.tmp / "a")
        self.b = make_wow(self.tmp / "b")

    def manager(self, addons=None):
        m = core.Manager(addons_dir=addons)
        p = mock.patch.object(m, "wow_running", return_value=False)
        p.start()
        self.addCleanup(p.stop)
        return m

    def setup_two(self):
        m = self.manager()
        m.set_addons_dir(self.a)
        self.assertEqual(m.add_installation(self.b, "Zweit"), (True, ""))
        return m

    def install_zip(self, m, name):
        z = make_zip(self.tmp / f"{name}.zip", {f"{name}/{name}.toc": "## Interface: 16001\n", f"{name}/{name}.lua": "x"})
        plan = m.plan_zip(z)
        res = m.apply([plan])
        self.assertTrue(res[0].ok, res[0].message)
        return res[0]


class MigrationTests(InstCase):
    def test_old_config_gets_installation_entry(self):
        write(self.wfa_home / "config.json", json.dumps({"addons_dir": str(self.a), "ignored": ["x"]}))
        m = self.manager()
        self.assertEqual(m.addons_dir, self.a)
        lst = m.installations()
        self.assertEqual(len(lst), 1)
        self.assertEqual((lst[0]["path"], lst[0]["active"], lst[0]["ok"]), (str(self.a), True, True))
        self.assertEqual(m.legacy_install(), str(self.a))
        saved = json.loads((self.wfa_home / "config.json").read_text("utf-8"))
        self.assertEqual(saved["ignored"], ["x"])
        self.assertEqual(len(saved["installations"]), 1)
        self.assertEqual(len(self.manager().installations()), 1)       # kein Duplikat beim naechsten Start

    def test_old_backups_without_marker_stay_usable(self):
        write(self.wfa_home / "config.json", json.dumps({"addons_dir": str(self.a)}))
        make_addon(self.wfa_home / "backups" / "20240101-000000", "Alt")
        make_addon(self.wfa_home / "sv_backups" / "20240101-000000" / "WTF" / "Account" / "X" / "SavedVariables", "SV")
        m = self.manager()
        self.assertEqual([b.name for b in m.list_backups()], ["20240101-000000"])
        self.assertEqual([b.folders for b in m.list_backups()], [["Alt"]])
        self.assertEqual(len(m.list_sv_backups()), 1)
        # nach dem Wechsel gehoeren sie weiter zur ersten Installation
        m.add_installation(self.b)
        self.assertTrue(m.switch_installation(self.b)[0])
        self.assertEqual(m.list_backups(), [])
        self.assertTrue(m.switch_installation(self.a)[0])
        self.assertEqual(len(m.list_backups()), 1)

    def test_old_snapshot_without_install_field(self):
        write(self.wfa_home / "config.json", json.dumps({"addons_dir": str(self.a)}))
        make_addon(self.a, "Alt")
        root = self.wfa_home / "snapshots"
        snap = wfa_snapshot.create(self.a, None, root)
        meta = snap.path / "meta.json"
        d = json.loads(meta.read_text("utf-8"))
        for k in ("install", "auto", "reason"):
            d.pop(k)
        meta.write_text(json.dumps(d), "utf-8")
        m = self.manager()
        old = wfa_snapshot.list_snapshots(root)[0]
        self.assertEqual((old.install, old.auto, old.reason), ("", False, ""))
        self.assertEqual(len(wfa_snapshot.list_snapshots(root, install=str(self.a), legacy=m.legacy_install())), 1)
        self.assertEqual(wfa_snapshot.list_snapshots(root, install=str(self.b), legacy=m.legacy_install()), [])
        wfa_snapshot.restore(old, self.a, None, root, legacy=m.legacy_install())
        with self.assertRaises(ValueError):
            wfa_snapshot.restore(old, self.b, None, root, legacy=m.legacy_install())


class ManageTests(InstCase):
    def test_add_remove_rename_switch(self):
        m = self.setup_two()
        names = {i["path"]: i for i in m.installations()}
        self.assertEqual(names[str(self.b)]["name"], "Zweit")
        self.assertFalse(names[str(self.b)]["active"])
        ok, hint = m.add_installation(self.b)
        self.assertFalse(ok)                                           # Duplikat
        self.assertFalse(m.add_installation(self.tmp / "nix")[0])
        self.assertFalse(m.remove_installation(self.a))                # aktive nicht entfernbar
        self.assertTrue(m.rename_installation(self.b, "Neu"))
        self.assertFalse(m.rename_installation(self.b, " "))
        self.assertTrue(m.switch_installation(self.b)[0])
        self.assertEqual(m.addons_dir, self.b)
        self.assertEqual(core.Manager().addons_dir, self.b)            # gespeichert
        self.assertFalse(m.switch_installation(self.tmp / "unbekannt")[0])
        self.assertTrue(m.remove_installation(self.a))
        self.assertEqual([i["name"] for i in m.installations()], ["Neu"])
        self.assertFalse(m.remove_installation(self.a))

    def test_switch_reads_client(self):
        write(self.a.parent.parent.parent / ".build.info", "Branch!STRING:0|Product!STRING:0|Version!STRING:0\neu|wowf|1.60.3.1\n")
        write(self.b.parent.parent.parent / ".build.info", "Branch!STRING:0|Product!STRING:0|Version!STRING:0\neu|wowf|1.61.0.1\n")
        m = self.setup_two()
        self.assertEqual(m.client_version, "1.60.3")
        m.switch_installation(self.b)
        self.assertEqual((m.client_version, m.client_interface), ("1.61.0", 16100))

    def test_session_override_not_saved(self):
        m = self.setup_two()
        m2 = self.manager(self.a)                                      # --addons-dir
        self.assertTrue(m2.switch_installation(self.b)[0])
        self.assertEqual(m2.addons_dir, self.b)
        self.assertEqual(core.Manager().addons_dir, self.a)

    def test_missing_folder_not_ok(self):
        m = self.setup_two()
        import shutil
        shutil.rmtree(self.b.parent.parent.parent)
        self.assertEqual([i["ok"] for i in m.installations()], [True, False])


class PerInstallationRecords(InstCase):
    def test_backups_and_restore_scoped(self):
        m = self.setup_two()
        r = self.install_zip(m, "Alpha")
        make_addon(self.a, "Alpha", version="2")                     # Update, damit ein Backup entsteht
        z = make_zip(self.tmp / "Alpha2.zip", {"Alpha/Alpha.toc": "## Interface: 16001\n## Version: 3\n"})
        res = m.apply([m.plan_zip(z)])
        bset = next(b for b in m.list_backups())
        self.assertEqual(bset.name, res[0].backup_set)
        self.assertEqual(bset.folders, ["Alpha"])
        m.switch_installation(self.b)
        self.assertEqual(m.list_backups(), [])
        foreign = core.BackupSet(bset.name, bset.path, 0, ["Alpha"])
        self.assertFalse(m.restore(foreign).ok)
        m.switch_installation(self.a)
        self.assertTrue(m.restore(m.list_backups()[0]).ok)

    def test_prune_is_per_installation(self):
        m = self.setup_two()
        for i in range(core.KEEP_BACKUPS + 2):
            d = m.paths.backups / f"2024010{i + 1}-000000"
            write(d / "F" / "f.txt", "x")
            m._mark_set(d)
        m.switch_installation(self.b)
        d = m._new_backup_dir()
        write(d / "G" / "g.txt", "x")
        m._prune_backups()
        self.assertEqual(len(m.list_backups()), 1)
        m.switch_installation(self.a)
        self.assertEqual(len(m.list_backups()), core.KEEP_BACKUPS)

    def test_sv_backups_scoped(self):
        m = self.setup_two()
        write(self.a.parent.parent / "WTF" / "Account" / "ACC" / "SavedVariables" / "Alpha.lua", "x")
        name = m.snapshot_sv()
        self.assertEqual([s.name for s in m.list_sv_backups()], [name])
        sset = m.list_sv_backups()[0]
        m.switch_installation(self.b)
        self.assertEqual(m.list_sv_backups(), [])
        self.assertFalse(m.restore_sv(sset).ok)

    def test_history_has_install(self):
        m = self.setup_two()
        m.add_history("Update", "k", "N", "1", "2", "CF", None)
        self.assertEqual(m.read_history(1)[0]["install"], str(self.a))

    def test_history_filtered_by_install(self):
        m = self.setup_two()
        m.add_history("Update", "k", "A", "1", "2", "CF", None)
        m.switch_installation(self.b)
        m.add_history("Update", "k", "B", "1", "2", "CF", None)
        self.assertEqual([h["name"] for h in m.read_history()], ["B"])
        self.assertEqual([h["name"] for h in m.read_history(all_installs=True)], ["B", "A"])
        m.switch_installation(self.a)
        self.assertEqual([h["name"] for h in m.read_history()], ["A"])

    def test_trash_scoped(self):
        root = self.tmp / "trash"
        write(self.a / "J" / "a.txt", "x")
        write(self.b / "K" / "a.txt", "x")
        wfa_cleanup.apply([wfa_cleanup.Finding("no_toc", self.a / "J", 1, "J")], self.a, root)
        wfa_cleanup.apply([wfa_cleanup.Finding("no_toc", self.b / "K", 1, "K")], self.b, root)
        mine = wfa_cleanup.list_sets(root, install=str(self.a))
        self.assertEqual(len(mine), 1)
        self.assertEqual(len(wfa_cleanup.list_sets(root)), 2)
        with self.assertRaises(ValueError):
            wfa_cleanup.restore_set(mine[0][0], install=str(self.b))
        self.assertEqual(wfa_cleanup.restore_set(mine[0][0], install=str(self.a)), [])
        self.assertTrue((self.a / "J" / "a.txt").exists())

    def test_trash_old_set_without_install_is_legacy(self):
        root = self.tmp / "trash"
        d = root / "20240101-000000"
        write(d / "manifest.json", json.dumps({"items": []}))
        self.assertEqual(len(wfa_cleanup.list_sets(root, install=str(self.a), legacy=str(self.a))), 1)
        self.assertEqual(wfa_cleanup.list_sets(root, install=str(self.b), legacy=str(self.a)), [])

    def test_addons_txt_backup_per_install(self):
        wtf = self.tmp / "WTF"
        write(wtf / "Account" / "ACC" / "Realm" / "Char" / "AddOns.txt", "A: enabled\n")
        ch = wfa_chars.list_characters(wtf)[0]
        wfa_chars.write_states_all([ch], {"A": False}, self.tmp / "bk", install=str(self.a))
        hits = list((self.tmp / "bk").glob("inst-*/ACC/Realm/Char/AddOns.txt"))
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].read_text(), "A: enabled\n")
        self.assertEqual(hits[0].parents[3].joinpath(".wfa-install").read_text(), str(self.a))
        wfa_chars.write_states_all([ch], {"A": True}, self.tmp / "bk2")        # alte Ablage unveraendert
        self.assertTrue((self.tmp / "bk2" / "ACC" / "Realm" / "Char" / "AddOns.txt").is_file())


class RefuterFixTests(InstCase):
    def test_symlink_does_not_duplicate(self):
        m = self.setup_two()
        wow = self.b.parents[2]                       # .../b ("World of Warcraft"-Ebene)
        os.symlink(wow, self.tmp / "lnk")
        ok, _hint = m.add_installation(self.tmp / "lnk")
        self.assertFalse(ok)
        self.assertEqual(len(m.installations()), 2)

    def test_removing_original_keeps_old_sets_away_from_others(self):
        write(self.wfa_home / "config.json", json.dumps({"addons_dir": str(self.a)}))
        m = self.manager()
        legacy = m.legacy_install()
        self.assertEqual(m.add_installation(self.b)[0], True)
        self.assertEqual(m.switch_installation(self.b)[0], True)
        self.assertTrue(m.remove_installation(self.a))
        self.assertEqual(m.legacy_install(), legacy)
        self.assertNotEqual(m.legacy_install(), m.install_id())

    def test_snapshot_suffix_sorts_numerically(self):
        S = wfa_snapshot.Snapshot
        ids = ["20261127-120000", "20261127-120000-2", "20261127-120000-9", "20261127-120000-10"]
        snaps = [mock.Mock(spec=S, id=i) for i in ids]
        self.assertEqual([s.id for s in sorted(snaps, key=wfa_snapshot._id_key, reverse=True)][0], "20261127-120000-10")
