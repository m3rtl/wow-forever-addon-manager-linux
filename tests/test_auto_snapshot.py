import json
from unittest import mock

import wfa_core as core
import wfa_snapshot as sn
from helpers import OfflineCase, build_info, make_addon, make_wow, make_zip, write


class AutoCase(OfflineCase):
    def setUp(self):
        super().setUp()
        self.addons = make_wow(self.tmp, build_info(("wowf", "1.60.3.1")))
        self.wow = self.addons.parent.parent.parent
        make_addon(self.addons, "Alpha")
        write(self.addons.parent.parent / "WTF" / "Account" / "ACC" / "SavedVariables" / "Alpha.lua", "x")
        self.mgr = core.Manager()
        self.mgr.set_addons_dir(self.addons)
        p = mock.patch.object(self.mgr, "wow_running", return_value=False)
        p.start()
        self.addCleanup(p.stop)

    def zip_plans(self, n):
        out = []
        for i in range(n):
            z = make_zip(self.tmp / f"Z{i}.zip", {f"Z{i}/Z{i}.toc": "## Interface: 16001\n"})
            out.append(self.mgr.plan_zip(z))
        return out

    def snaps(self):
        return sn.list_snapshots(self.mgr.snapshot_root)


class RotationTests(AutoCase):
    def test_fields_and_separate_rotation(self):
        root = self.tmp / "snaps"
        manual = [sn.create(self.addons, None, root, label=f"m{i}") for i in range(3)]
        for i in range(4):
            sn.create(self.addons, None, root, label=f"a{i}", auto=True, reason=f"r{i}")
        snaps = sn.list_snapshots(root)
        autos = [s for s in snaps if s.auto]
        self.assertEqual(len(autos), 2)
        self.assertEqual(sorted(s.reason for s in autos), ["r2", "r3"])
        self.assertEqual({s.id for s in snaps if not s.auto}, {s.id for s in manual})     # auto verdraengt nie manuelle
        self.assertTrue(all(s.install == str(self.addons) for s in snaps))
        sn.create(self.addons, None, root, label="m3")
        self.assertEqual(len([s for s in sn.list_snapshots(root) if not s.auto]), 3)
        self.assertEqual(len([s for s in sn.list_snapshots(root) if s.auto]), 2)

    def test_rotation_per_installation(self):
        root = self.tmp / "snaps"
        other = make_wow(self.tmp / "o")
        for _ in range(3):
            sn.create(self.addons, None, root, auto=True)
        sn.create(other, None, root, auto=True)
        self.assertEqual(len(sn.list_snapshots(root, install=str(other))), 1)
        self.assertEqual(len(sn.list_snapshots(root, install=str(self.addons))), 2)


class ManagerAutoTests(AutoCase):
    def test_auto_snapshot_never_raises(self):
        s = self.mgr.auto_snapshot("Grund")
        self.assertTrue(s.auto)
        self.assertEqual((s.reason, s.client, s.install), ("Grund", "1.60.3", str(self.addons)))
        self.assertEqual(s.addons, ["Alpha"])
        with mock.patch("wfa_snapshot.create", side_effect=OSError("voll")):
            self.assertIsNone(self.mgr.auto_snapshot("x"))

    def test_before_update_threshold(self):
        self.mgr.cfg["auto_snapshot_min"] = 2
        plans = self.zip_plans(1)
        self.mgr.apply(plans)
        self.assertEqual(self.snaps(), [])
        plans = self.zip_plans(2)
        res = self.mgr.apply(plans)
        self.assertTrue(all(r.ok for r in res))
        snaps = self.snaps()
        self.assertEqual(len(snaps), 1)
        self.assertTrue(snaps[0].auto)
        self.assertIn("2", snaps[0].reason)

    def test_threshold_zero_is_off(self):
        self.mgr.cfg["auto_snapshot_min"] = 0
        self.mgr.apply(self.zip_plans(3))
        self.assertEqual(self.snaps(), [])

    def test_client_change(self):
        m = self.mgr
        self.assertIsNone(m.check_client_change())                       # set_addons_dir/erste Pruefung: nur merken
        self.assertEqual(m.cfg["client_seen"][str(self.addons)], "1.60.3")
        self.assertIsNone(m.check_client_change())
        self.assertEqual(self.snaps(), [])
        write(self.wow / ".build.info", build_info(("wowf", "1.60.4.1")))
        m._read_client()
        self.assertEqual(m.check_client_change(), ("1.60.3", "1.60.4"))
        self.assertEqual(json.loads(m.paths.config_file.read_text("utf-8"))["client_seen"][str(self.addons)], "1.60.4")
        snaps = self.snaps()
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0].reason, "Client 1.60.3 -> 1.60.4")
        self.assertIsNone(m.check_client_change())                       # nur einmal

    def test_client_change_without_snapshot_setting(self):
        m = self.mgr
        m.check_client_change()
        m.cfg["auto_snapshot_client"] = False
        write(self.wow / ".build.info", build_info(("wowf", "1.61.0.1")))
        m._read_client()
        self.assertEqual(m.check_client_change(), ("1.60.3", "1.61.0"))
        self.assertEqual(self.snaps(), [])

    def test_scan_checks_client_and_exposes_change(self):
        self.mgr.scan()
        self.assertIsNone(self.mgr.take_client_change())
        write(self.wow / ".build.info", build_info(("wowf", "1.60.9.1")))
        self.mgr.scan()
        self.assertEqual(self.mgr.take_client_change(), ("1.60.3", "1.60.9"))
        self.assertIsNone(self.mgr.take_client_change())
        self.assertEqual(len(self.snaps()), 1)


class ApiTests(AutoCase):
    def test_reason_kind_and_data(self):
        self.mgr.cfg["auto_snapshot_min"] = 2
        self.mgr.apply(self.zip_plans(2))
        s = self.snaps()[0]
        self.assertEqual((s.reason_kind, s.reason_data), ("bulk", {"n": 2}))
        self.mgr.check_client_change()
        write(self.wow / ".build.info", build_info(("wowf", "1.60.4.1")))
        self.mgr._read_client()
        self.mgr.check_client_change()
        c = next(x for x in self.snaps() if x.reason_kind == "client")
        self.assertEqual(c.reason_data, {"old": "1.60.3", "new": "1.60.4"})
        self.assertEqual(self.mgr.last_client_change, ("1.60.3", "1.60.4"))
        self.assertEqual(self.mgr.create_snapshot("L").reason_kind, "manual")

    def test_manager_snapshot_api_scoped(self):
        other = make_wow(self.tmp / "o")
        s = self.mgr.create_snapshot("Mein")
        self.assertEqual([x.id for x in self.mgr.list_snapshots()], [s.id])
        make_addon(self.addons, "Neu")
        safety = self.mgr.restore_snapshot(s)
        self.assertFalse((self.addons / "Neu").exists())
        self.assertEqual(safety.label, "Vor Wiederherstellung")
        self.mgr.add_installation(other)
        self.mgr.switch_installation(other)
        self.assertEqual(self.mgr.list_snapshots(), [])
        with self.assertRaises(ValueError):
            self.mgr.restore_snapshot(s)

    def test_failure_goes_to_notes(self):
        with mock.patch("wfa_snapshot.create", side_effect=OSError("voll")):
            self.assertIsNone(self.mgr.auto_snapshot("x"))
        self.assertTrue(any("voll" in n for n in self.mgr.snapshot_notes))
        self.mgr.check([])   # check() leert notes, nicht snapshot_notes
        self.assertTrue(any("voll" in n for n in self.mgr.snapshot_notes))
        self.mgr.auto_snapshot("y")   # Erfolg raeumt die Notiz ab
        self.assertEqual(self.mgr.snapshot_notes, [])

    def test_set_addons_dir_adds_and_activates(self):
        other = make_wow(self.tmp / "o")
        self.mgr.set_addons_dir(other)
        self.assertEqual(self.mgr.addons_dir, other)
        self.assertEqual(sorted(i["path"] for i in self.mgr.installations()), sorted([str(self.addons), str(other)]))
        self.mgr.set_addons_dir(other)
        self.assertEqual(len(self.mgr.installations()), 2)
