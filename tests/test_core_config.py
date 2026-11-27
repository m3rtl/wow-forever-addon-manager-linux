import json
import os
import stat
import unittest

import wfa_core as core
from helpers import OfflineCase, write


class ConfigTests(OfflineCase):
    def test_paths_use_wfa_home(self):
        p = core.Paths()
        self.assertEqual(p.config_file, self.wfa_home / "config.json")
        self.assertEqual(p.backups, self.wfa_home / "backups")

    def test_defaults_and_roundtrip(self):
        cfg = core.Config(core.Paths())
        self.assertEqual(cfg["check_interval_min"], 60)
        self.assertIsNone(cfg["download_dir"])
        cfg["include_beta"] = True
        cfg.save()
        again = core.Config(core.Paths())
        self.assertTrue(again["include_beta"])

    def test_save_permissions_0600(self):
        cfg = core.Config(core.Paths())
        cfg.save()
        mode = stat.S_IMODE(os.stat(core.Paths().config_file).st_mode)
        self.assertEqual(mode, 0o600)
        self.assertFalse(core.Paths().config_file.with_name("config.json.tmp").exists())

    def test_broken_file_is_kept_as_bad(self):
        write(self.wfa_home / "config.json", "{kaputt")
        logs = []
        cfg = core.Config(core.Paths(), logs.append)
        self.assertEqual(cfg["check_interval_min"], 60)
        bad = self.wfa_home / "config.json.bad"
        self.assertEqual(bad.read_text(), "{kaputt")
        self.assertEqual(stat.S_IMODE(os.stat(bad).st_mode), 0o600)
        self.assertTrue(logs)

    def test_non_object_json_is_rejected(self):
        write(self.wfa_home / "config.json", "[1, 2]")
        self.assertEqual(core.Config(core.Paths())["packages"], {})

    def test_wrong_types_fall_back_and_unknown_kept(self):
        write(self.wfa_home / "config.json", json.dumps(
            {"include_beta": "ja", "check_interval_min": 5, "ignored": {}, "zukunft": 7, "download_dir": ""}))
        cfg = core.Config(core.Paths())
        self.assertFalse(cfg["include_beta"])
        self.assertEqual(cfg["check_interval_min"], 60)
        self.assertEqual(cfg["ignored"], [])
        self.assertEqual(cfg["zukunft"], 7)
        self.assertIsNone(cfg["download_dir"])

    def test_defaults_are_not_shared(self):
        a, b = core.Config(core.Paths()), core.Config(core.Paths())
        a["packages"]["x"] = 1
        self.assertEqual(b["packages"], {})

    def test_api_key_env_wins(self):
        cfg = core.Config(core.Paths())
        cfg["curseforge_api_key"] = " cfgkey "
        self.assertEqual(cfg.api_key, "cfgkey")
        os.environ["CF_API_KEY"] = "envkey"
        self.assertEqual(cfg.api_key, "envkey")


if __name__ == "__main__":
    unittest.main()
