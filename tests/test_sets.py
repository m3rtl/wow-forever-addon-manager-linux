"""Addon-Sets: Verwaltung, Plan mit Pflichtabhaengigkeiten, Anwenden auf AddOns.txt."""
import tempfile
import unittest
from pathlib import Path

from helpers import OfflineCase, make_addon, write
import wfa_chars as ch
import wfa_sets as sets


class FakeCfg(dict):
    saved = 0

    def save(self):
        self.saved += 1


class SetTests(unittest.TestCase):
    def setUp(self):
        self.cfg = FakeCfg(addon_sets={})

    def test_crud(self):
        sets.save_set(self.cfg, "Raid", ["b", "A", "b"])
        self.assertEqual(sets.get_set(self.cfg, "Raid"), ["A", "b"])
        created = self.cfg["addon_sets"]["Raid"]["created"]
        sets.save_set(self.cfg, "Raid", ["x"])
        self.assertEqual(self.cfg["addon_sets"]["Raid"]["created"], created)
        sets.save_set(self.cfg, "alpha", [])
        self.assertEqual(sets.list_sets(self.cfg), ["alpha", "Raid"])
        self.assertTrue(sets.rename_set(self.cfg, "Raid", "PvP"))
        self.assertFalse(sets.rename_set(self.cfg, "Raid", "X"))
        self.assertFalse(sets.rename_set(self.cfg, "PvP", "alpha"))
        self.assertIsNone(sets.get_set(self.cfg, "Raid"))
        sets.delete_set(self.cfg, "PvP")
        sets.delete_set(self.cfg, "nope")
        self.assertEqual(sets.list_sets(self.cfg), ["alpha"])
        self.assertGreater(self.cfg.saved, 4)

    def test_from_states(self):
        got = sets.set_from_states({"A": False, "b": True}, ["a", "B", "C"])
        self.assertEqual(got, ["B", "C"])


class PlanTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.addons = self.tmp / "AddOns"
        make_addon(self.addons, "Main", extra_toc="## RequiredDeps: LibX\n")
        make_addon(self.addons, "LibX", extra_toc="## Dependencies: LibY\n")
        make_addon(self.addons, "LibY", extra_toc="## Dependencies: Main\n")   # Zyklus
        make_addon(self.addons, "Other")
        (self.addons / "NoToc").mkdir()

    def test_plan(self):
        plan = sets.plan_set(["Main", "Gone"], self.addons, 16001)
        self.assertEqual(plan.changes, {"LibX": True, "LibY": True, "Main": True, "Other": False})
        self.assertEqual(plan.missing, ["Gone"])
        self.assertEqual(plan.deps_added, ["LibX", "LibY"])

    def test_plan_empty_and_case(self):
        self.assertTrue(not any(sets.plan_set([], self.addons, 16001).changes.values()))
        self.assertTrue(sets.plan_set(["other"], self.addons, 16001).changes["Other"])

    def test_apply(self):
        wtf = self.tmp / "WTF"
        write(wtf / "Account" / "A#1" / "Realm" / "Zed" / "AddOns.txt", "Other: enabled\nMain: disabled\n")
        chars = ch.list_characters(wtf)
        plan = sets.plan_set(["Main"], self.addons, 16001)
        sets.apply_set(plan, chars, self.tmp / "bak")
        st = ch.read_states(chars[0])
        self.assertTrue(st["Main"] and st["LibX"])
        self.assertFalse(st["Other"])


if __name__ == "__main__":
    unittest.main()
