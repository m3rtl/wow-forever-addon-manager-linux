"""CLI: Sets, Fehleranalyse, Installationen (offline, WoW-Pruefung gemockt)."""
import contextlib
import io
import unittest
from unittest import mock

import wfa_cli
import wfa_core as core
import wfa_sets
from helpers import OfflineCase, make_addon, make_wow, write

BUGS = r'''BugGrabberDB = {
	["session"] = 1,
	["errors"] = {
		{
			["message"] = "Interface\\AddOns\\Alpha\\Alpha.lua:7: boom",
			["time"] = "2026/03/02 11:00:00",
			["counter"] = 2,
		},
	},
}
'''


class CliExtraCase(OfflineCase):
    def setUp(self):
        super().setUp()
        self.addons = make_wow(self.tmp)
        make_addon(self.addons, "Alpha")
        make_addon(self.addons, "Beta")
        self.wtf = self.addons.parent.parent / "WTF"
        self.chars = []
        for name in ("Aaa", "Bbb"):
            f = write(self.wtf / "Account" / "ACC" / "Realm" / name / "AddOns.txt", "Alpha: enabled\nBeta: enabled\n")
            self.chars.append(f)
        mgr = core.Manager(addons_dir=self.addons)
        wfa_sets.save_set(mgr.cfg, "Mini", ["Alpha"])
        self.running = mock.patch.object(core.Manager, "wow_running", return_value=False)
        self.running.start()
        self.addCleanup(self.running.stop)

    def cli(self, *args, addons=True):
        argv = (["--addons-dir", str(self.addons)] if addons else []) + list(args)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = wfa_cli.main(argv)
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_sets_lists(self):
        code, out, _e = self.cli("--sets")
        self.assertEqual(code, 0)
        self.assertIn("Mini  1 Addon", out)

    def test_sets_empty(self):
        mgr = core.Manager(addons_dir=self.addons)
        wfa_sets.delete_set(mgr.cfg, "Mini")
        code, out, _e = self.cli("--sets")
        self.assertIn("Keine Sets vorhanden.", out)

    def test_set_applies_to_all(self):
        code, out, _e = self.cli("--set", "Mini")
        self.assertEqual(code, 0, _e)
        self.assertIn("2 Charaktere: 1 an, 1 aus", out)
        for f in self.chars:
            txt = f.read_text()
            self.assertIn("Alpha: enabled", txt)
            self.assertIn("Beta: disabled", txt)

    def test_set_single_char(self):
        code, out, _e = self.cli("--set", "Mini", "--char", "bbb-realm")
        self.assertEqual(code, 0, _e)
        self.assertIn("1 Charaktere", out)
        self.assertIn("enabled", self.chars[0].read_text())
        self.assertNotIn("Beta: enabled", self.chars[1].read_text())
        self.assertIn("Beta: enabled", self.chars[0].read_text())

    def test_set_unknown_char_and_set(self):
        code, _o, err = self.cli("--set", "Mini", "--char", "Zzz-Realm")
        self.assertEqual(code, 1)
        self.assertIn("Charakter nicht gefunden: Zzz-Realm", err)
        code, _o, err = self.cli("--set", "Nope")
        self.assertEqual(code, 1)
        self.assertIn("Set nicht gefunden: Nope. Vorhanden: Mini", err)

    def test_set_refused_when_wow_runs(self):
        core.Manager.wow_running.return_value = True
        code, _o, err = self.cli("--set", "Mini")
        self.assertEqual(code, 2)
        self.assertIn("WoW läuft", err)
        self.assertIn("Beta: enabled", self.chars[0].read_text())

    def test_char_needs_set(self):
        code, _o, _e = self.cli("--char", "Aaa-Realm")
        self.assertEqual(code, 2)

    def test_errors_not_installed(self):
        code, out, _e = self.cli("--errors")
        self.assertEqual(code, 1)
        self.assertIn("!BugGrabber ist nicht installiert", out)

    def test_errors_groups_and_samples(self):
        make_addon(self.addons, "!BugGrabber")
        code, out, _e = self.cli("--errors")
        self.assertEqual(code, 0)
        self.assertIn("Noch keine Fehlerdaten", out)
        write(self.wtf / "Account" / "ACC" / "SavedVariables" / "!BugGrabber.lua", BUGS)
        code, out, _e = self.cli("--errors")
        self.assertEqual(code, 0, _e)
        self.assertIn("2 Fehler in 1 Addon", out)
        self.assertIn("Alpha", out)
        self.assertNotIn("boom", out)
        code, out, _e = self.cli("--errors", "alpha")
        self.assertIn("boom", out)
        code, out, _e = self.cli("--errors", "gibtsnicht")
        self.assertEqual(code, 0)   # Analyse lief, nur ohne Treffer
        self.assertIn("kein Update im Verlauf", self.cli("--errors")[1])

    def test_installations_and_use(self):
        other = make_wow(self.tmp / "zweite")
        mgr = core.Manager()
        mgr.set_addons_dir(str(self.addons))
        ok, _h = mgr.add_installation(str(other), "Zweite")
        self.assertTrue(ok)
        code, out, _e = self.cli("--installations", addons=False)
        self.assertEqual(code, 0)
        self.assertIn("Zweite", out)
        self.assertEqual(sum(1 for l in out.splitlines() if l.startswith("*")), 1)
        code, out, _e = self.cli("--use", "zweite", addons=False)
        self.assertEqual(code, 0, _e)
        self.assertIn("Aktive Installation: Zweite", out)
        self.assertEqual(core.Manager().install_id(), str(other))
        code, out, err = self.cli("--use", "gibtsnicht", addons=False)
        self.assertEqual(code, 1)
        self.assertIn("Zweite", out)

    def test_use_with_addons_dir_rejected(self):
        code, out, err = self.cli("--use", "x")
        self.assertEqual(code, 1)
        self.assertIn("--addons-dir", err)

    def test_use_ambiguous_name(self):
        o1, o2 = make_wow(self.tmp / "z1"), make_wow(self.tmp / "z2")
        mgr = core.Manager(addons_dir=self.addons)
        mgr.add_installation(str(o1), "Gleich")
        mgr.add_installation(str(o2), "Gleich")
        before = core.Manager().install_id()
        code, out, err = self.cli("--use", "gleich", addons=False)
        self.assertEqual(code, 1)
        self.assertIn(str(o1), out)
        self.assertIn(str(o2), out)
        self.assertEqual(core.Manager().install_id(), before)
        code, out, err = self.cli("--use", str(o2), addons=False)
        self.assertEqual(code, 0, err)

    def test_menu_installation_switch(self):
        other = make_wow(self.tmp / "zweite")
        mgr = core.Manager(addons_dir=self.addons)
        mgr.add_installation(str(other), "Zweite")
        names = [i["name"] for i in mgr.installations()]
        n = names.index("Zweite") + 1
        with mock.patch.object(wfa_cli, "ask", return_value=str(n)), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(wfa_cli.menu_installation(mgr))
        self.assertEqual(mgr.install_id(), str(other))

    def test_status_text_stale(self):
        import wfa_health
        mgr = core.Manager(addons_dir=self.addons)
        p = mock.Mock(status=core.CURRENT)
        self.assertEqual(wfa_cli.status_cell(p, wfa_health.Health("abandoned"))[0], "⚠ verwaist")
        self.assertEqual(wfa_cli.status_cell(p, wfa_health.Health("stale"))[0], "◷ lange kein Update")
        self.assertEqual(wfa_cli.status_cell(mock.Mock(status=core.UPDATE), wfa_health.Health("stale"))[0], core.UPDATE)


if __name__ == "__main__":
    unittest.main()
