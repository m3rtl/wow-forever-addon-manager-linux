import os
import threading
from unittest import mock

import wfa_apply
import wfa_cli
import wfa_core as core
import wfa_unattended as un
from helpers import OfflineCase, make_addon, make_wow


def pkg(name, status=core.UPDATE, ignored=False):
    p = core.Package(f"k-{name}", name, [name], "1", "ok", "CF", core.Remote("2", "2", "CF", None, 5, "f.zip"), status)
    p.ignored = ignored
    return p


def plan(name, strong=False):
    return core.InstallPlan(f"k-{name}", name, "CF", "1", "2", [name], [], [], strong, None, {})


class UnattendedCase(OfflineCase):
    def setUp(self):
        super().setUp()
        self.addons = make_wow(self.tmp)
        make_addon(self.addons, "Alpha")
        self.mgr = core.Manager(addons_dir=self.addons)
        self.out = []
        self.patch(self.mgr, "wow_running", return_value=False)
        self.patch(self.mgr, "discard")

    def patch(self, obj, name, **kw):
        p = mock.patch.object(obj, name, **kw)
        m = p.start()
        self.addCleanup(p.stop)
        return m

    def run_update(self, **kw):
        return un.run_update(self.mgr, log=self.out.append, **kw)


class RunUpdateTests(UnattendedCase):
    def test_skipped_when_wow_runs(self):
        self.mgr.wow_running.return_value = True
        scan = self.patch(self.mgr, "scan")
        r = self.run_update()
        self.assertEqual((r.exit_code, r.updated, r.failed), (2, [], []))
        self.assertTrue(r.skipped)
        scan.assert_not_called()

    def test_unknown_running_state_still_updates(self):
        self.mgr.wow_running.return_value = None
        self.patch(self.mgr, "scan", return_value=[pkg("Alpha", core.CURRENT)])
        self.patch(self.mgr, "check")
        r = self.run_update()
        self.assertEqual((r.exit_code, r.skipped), (0, None))

    def test_nothing_to_do(self):
        self.patch(self.mgr, "scan", return_value=[pkg("Alpha", core.CURRENT)])
        self.patch(self.mgr, "check")
        apply = self.patch(self.mgr, "apply")
        r = self.run_update()
        self.assertEqual((r.exit_code, r.updated, r.failed, r.skipped), (0, [], [], None))
        apply.assert_not_called()
        self.assertEqual(self.out[-1], "Alle Addons aktuell.")

    def test_updates_respect_ignored_and_deps(self):
        pk = [pkg("Alpha"), pkg("Beta", ignored=True), pkg("Held", core.HELD)]
        self.patch(self.mgr, "scan", return_value=pk)
        self.patch(self.mgr, "check")
        self.patch(self.mgr, "plan_update", side_effect=lambda p: plan(p.name))
        dep = core.DepNeed("Lib", "benötigt von Alpha", core.Candidate("CF", 9, "Lib"), via="cf")
        toc = core.DepNeed("Nur", "x", None, via="toc")
        res_dep = self.patch(self.mgr, "resolve_deps", return_value=[dep, toc])
        self.patch(self.mgr, "plan_candidate", side_effect=lambda c: plan(c.name))
        apply = self.patch(self.mgr, "apply",
                           side_effect=lambda plans, origin=None: [core.Result(p.key, p.name, True, "") for p in plans])
        r = self.run_update(quiet=True)
        self.assertEqual((r.exit_code, r.updated, r.failed), (0, ["Alpha", "Lib"], []))
        self.assertEqual(apply.call_args.kwargs["origin"], "auto")
        self.assertTrue(res_dep.call_args.kwargs["cf_only"])
        self.assertEqual(len(self.out), 1)                 # quiet: nur die Zusammenfassung
        self.assertIn("2 Addons aktualisiert", self.out[0])

    def test_failures_give_exit_1(self):
        self.patch(self.mgr, "scan", return_value=[pkg("Alpha"), pkg("Bad"), pkg("Strong"), pkg("Err", core.ERROR)])
        self.mgr.check = mock.Mock()
        self.patch(self.mgr, "plan_update",
                   side_effect=lambda p: (_ for _ in ()).throw(core.ApiError("kaputt")) if p.name == "Bad" else plan(p.name, p.name == "Strong"))
        self.patch(self.mgr, "resolve_deps", return_value=[])
        self.patch(self.mgr, "apply", side_effect=lambda plans, origin=None: [core.Result(p.key, p.name, False, "voll") for p in plans])
        r = self.run_update()
        self.assertEqual(r.exit_code, 1)
        names = [n for n, _m in r.failed]
        self.assertEqual(sorted(names), ["Alpha", "Bad", "Err", "Strong"])
        self.assertEqual(r.updated, [])

    def test_timeout_does_not_block(self):
        self.patch(self.mgr, "scan", return_value=[pkg("Alpha")])
        release = threading.Event()
        self.addCleanup(release.set)
        self.patch(self.mgr, "check", side_effect=lambda *a, **k: release.wait(5))
        apply = self.patch(self.mgr, "apply")
        r = self.run_update(timeout=0.3)
        self.assertEqual(r.exit_code, 1)
        self.assertEqual(r.failed[0][0], "Zeitlimit")
        self.assertTrue(self.mgr.dl_cancel.is_set())
        apply.assert_not_called()

    def test_scan_error_is_reported(self):
        self.patch(self.mgr, "scan", side_effect=core.ApiError("netz"))
        r = self.run_update()
        self.assertEqual((r.exit_code, r.failed), (1, [("Prüfung", "netz")]))

    def test_needs_setup(self):
        r = un.run_update(core.Manager(), log=self.out.append)
        self.assertEqual(r.exit_code, 1)


class WowRunningTests(UnattendedCase):
    def test_own_process_tree_does_not_count(self):
        m = core.Manager(addons_dir=self.addons)
        cp = mock.Mock(returncode=0, stdout=f"{os.getpid()}\n".encode())
        with mock.patch("subprocess.run", return_value=cp):
            self.assertFalse(m.wow_running())
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout=f"{os.getpid()}\n4999999\n".encode())):
            self.assertTrue(m.wow_running())
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=1, stdout=b"")):
            self.assertFalse(m.wow_running())
        parents = wfa_apply._own_pids()
        self.assertIn(os.getpid(), parents)
        self.assertIn(os.getppid(), parents)


class LaunchTests(UnattendedCase):
    def test_launch_command_kinds(self):
        self.assertEqual(un.launch_command(flatpak=True), "flatpak run io.github.m3rtl.WowForeverAddonManager")
        with mock.patch("wfa_unattended.install_kind", return_value="source"):
            self.assertTrue(un.launch_command().endswith("start.sh"))
            self.assertNotIn("flatpak", un.launch_command(flatpak=False))
        with mock.patch("wfa_unattended.install_kind", return_value="flatpak"):
            self.assertEqual(un.launch_command(), "flatpak run io.github.m3rtl.WowForeverAddonManager")
        with mock.patch("wfa_unattended.install_kind", return_value="binary"), mock.patch("sys.executable", "/opt/a b/wfa"):
            self.assertEqual(un.launch_command(), "'/opt/a b/wfa'")

    def test_prelaunch_script(self):
        p = un.write_prelaunch_script(self.tmp / "sub" / "pre.sh")
        self.assertEqual(oct(p.stat().st_mode & 0o777), "0o755")
        lines = p.read_text().splitlines()
        self.assertEqual(lines[0], "#!/bin/sh")
        self.assertEqual(lines[1], un.launch_command() + " --update --quiet")


class CliTests(UnattendedCase):
    def run_main(self, *argv, result=None, exec_side=None):
        result = result or un.UnattendedResult()
        with mock.patch("wfa_unattended.run_update", return_value=result) as ru, \
                mock.patch("os.execvp", side_effect=exec_side) as ex, mock.patch("sys.stdout"):
            code = wfa_cli.main(["--addons-dir", str(self.addons), *argv])
        return code, ru, ex

    def test_update_only(self):
        code, ru, ex = self.run_main("--update", "--quiet", result=un.UnattendedResult(exit_code=2, skipped="x"))
        self.assertEqual(code, 2)
        self.assertTrue(ru.call_args.kwargs["quiet"])
        ex.assert_not_called()

    def test_run_execs_rest_even_after_failed_update(self):
        code, ru, ex = self.run_main("--update", "--run", "echo", "hi", "--x",
                                     result=un.UnattendedResult(failed=[("A", "b")], exit_code=1))
        ex.assert_called_once_with("echo", ["echo", "hi", "--x"])
        ru.assert_called_once()

    def test_run_implies_update(self):
        code, ru, ex = self.run_main("--run", "game")
        ru.assert_called_once()
        ex.assert_called_once_with("game", ["game"])

    def test_run_exception_in_update_still_execs(self):
        with mock.patch("wfa_unattended.run_update", side_effect=RuntimeError("boom")), \
                mock.patch("os.execvp") as ex, mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            wfa_cli.main(["--addons-dir", str(self.addons), "--update", "--run", "game"])
        ex.assert_called_once_with("game", ["game"])

    def test_run_command_missing(self):
        code, _ru, _ex = self.run_main("--run", "gibtsnicht", exec_side=FileNotFoundError("nix"))
        self.assertEqual(code, 127)

    def test_flag_errors(self):
        for argv in (["--quiet"], ["--run"]):
            with self.assertRaises(SystemExit) as cm, mock.patch("sys.stderr"):
                wfa_cli.main(argv)
            self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    import unittest
    unittest.main()
