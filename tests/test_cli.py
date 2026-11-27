import os
import subprocess
import sys
import unittest

import wfa_core as core
from helpers import ROOT, OfflineCase


class CliTests(OfflineCase):
    def run_cli(self, *args):
        env = dict(os.environ, WOW_FA_HOME=str(self.wfa_home))
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
        return subprocess.run([sys.executable, str(ROOT / "wow-forever-addon-manager.py"), *args],
                              capture_output=True, text=True, timeout=30, env=env, cwd=self.tmp)

    def test_version(self):
        r = self.run_cli("--version")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), f"wow-forever-addon-manager {core.__version__}")

    def test_help_lists_options(self):
        r = self.run_cli("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        for opt in ("--cli", "--check", "--addons-dir", "--export", "--import"):
            self.assertIn(opt, r.stdout)

    def test_unknown_option_fails(self):
        r = self.run_cli("--cli", "--gibt-es-nicht")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
