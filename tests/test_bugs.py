import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

import wfa_i18n
import wfa_bugs as b

wfa_i18n.setup("de")


def _w(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode())


SAMPLE = r'''
-- Kommentar
BugGrabberDB = {
	["session"] = 12,
	["lastSanitation"] = 3,
	["errors"] = {
		{
			["message"] = "[string \"@Interface/AddOns/Foo/Core.lua\"]:12: attempt to index nil\nzweite Zeile",
			["stack"] = "Interface\\AddOns\\Foo\\libs\\LibStub\\LibStub.lua:5: in function <...>\n[C]: ?",
			["locals"] = {
				["a"] = { [1] = "x", [2] = { ["deep"] = true }, n = 2 },
			},
			["time"] = "2026/03/01 10:00:00",
			["session"] = 12,
			["counter"] = 3,
		}, -- [1]
		{
			["message"] = "Interface\\AddOns\\Bar\\Bar.lua:7: boom",
			["stack"] = [==[
long ]] string with "quotes" and \n literal]==],
			["time"] = "2026/03/02 11:00:00",
			["session"] = 12,
		}, -- [2]
		{
			["message"] = 42,
			["counter"] = "5",
			["time"] = "kaputt",
		}, -- [3]
	},
}
'''


class ParserTests(unittest.TestCase):
    def test_sample(self):
        errs = [e for e, _t in b.parse_bug_grabber(SAMPLE)]
        self.assertEqual(len(errs), 3)
        e1, e2, e3 = errs
        self.assertTrue(e1.message.startswith('[string "@Interface/AddOns/Foo/Core.lua"]:12:'))
        self.assertIn("zweite Zeile", e1.message)
        self.assertEqual(e1.folders, ["Foo"])
        self.assertEqual(e1.count, 3)
        self.assertEqual(e1.time, datetime(2026, 3, 1, 10, 0, 0))
        self.assertEqual(e1.session, 12)
        self.assertEqual(e2.folders, ["Bar"])
        self.assertEqual(e2.count, 1)
        self.assertIn('long ]] string with "quotes" and \\n literal', e2.stack)
        self.assertEqual(e3.message, "42")
        self.assertEqual(e3.count, 5)
        self.assertIsNone(e3.time)
        self.assertIsNone(e3.session)
        self.assertEqual(e3.folders, [])

    def test_folders_from_stack_and_libs(self):
        self.assertEqual(b.folders_in("a Interface\\AddOns\\X\\Libs\\Ace\\Ace.lua:1 und Interface/AddOns/Y/z.lua"), ["X", "Y"])
        self.assertEqual(b.folders_in("nix"), [])

    def test_literals(self):
        v, ok = b.parse_lua_assignments('A = "x\\65\\x42\\u{43}\\z\n   y"\nB = {1, 2; 3, k = -1.5e2, [10] = 0x1F, t = true, f = false, n = nil}\nC = \'s\\\'q\'')
        self.assertTrue(ok)
        self.assertEqual(v["A"], "xABCy")
        self.assertEqual(v["B"][1:4:1] if False else [v["B"][i] for i in (1, 2, 3)], [1, 2, 3])
        self.assertEqual(v["B"]["k"], -150.0)
        self.assertEqual(v["B"][10], 31)
        self.assertIs(v["B"]["t"], True)
        self.assertIs(v["B"]["f"], False)
        self.assertNotIn("n", v["B"])
        self.assertEqual(v["C"], "s'q")

    def test_utf8_bytes(self):
        v, _ = b.parse_lua_assignments('A = "K\\195\\164se"')
        self.assertEqual(v["A"], "Käse")

    def test_comments(self):
        v, ok = b.parse_lua_assignments("--[[ block\n x = 1 ]] A = 1 --[==[ y ]==] B = { --c\n 2 }")
        self.assertTrue(ok)
        self.assertEqual(v["A"], 1)
        self.assertEqual(v["B"], {1: 2})

    def test_truncated(self):
        cut = SAMPLE[:SAMPLE.index('["message"] = 42')] 
        errs = [e for e, _t in b.parse_bug_grabber(cut)]
        self.assertEqual(len(errs), 2)
        mid = SAMPLE[:SAMPLE.index("zweite")]
        b.parse_bug_grabber(mid)   # darf nicht abstuerzen
        for n in (0, 5, 40, 200, 700):
            b.parse_bug_grabber(SAMPLE[:n])

    def test_garbage_and_depth(self):
        self.assertEqual(b.parse_bug_grabber("\x00\x01 garbage = = {"), [])
        self.assertEqual(b.parse_bug_grabber(""), [])
        deep = "BugGrabberDB = {errors = {{message='m'}}, x = " + "{" * 500
        self.assertEqual(len(b.parse_bug_grabber(deep)), 1)
        self.assertEqual(b.parse_bug_grabber("BugGrabberDB = {errors = 5}"), [])
        self.assertEqual(b.parse_bug_grabber("BugGrabberDB = {errors = {5, 'x', {}}}"), [])

    def test_unterminated_string(self):
        self.assertEqual(len(b.parse_bug_grabber('BugGrabberDB = {errors = {{message="ok"},{message="abc')), 1)

    def test_performance(self):
        one = ('{["message"]="Interface\\\\AddOns\\\\Foo\\\\a.lua:%d: err",["stack"]="s\\ns",'
               '["locals"]={["x"]={1,2,{["y"]="z"}}},["time"]="2026/03/01 10:00:%02d",["session"]=1,["counter"]=2},')
        text = "BugGrabberDB = {errors = {" + "".join(one % (i, i % 60) for i in range(2000)) + "}}"
        t0 = time.perf_counter()
        errs = b.parse_bug_grabber(text)
        self.assertLess(time.perf_counter() - t0, 2.0)
        self.assertEqual(len(errs), 2000)


class LoadTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.root = Path(self._t.name)

    def test_installed(self):
        ad = self.root / "AddOns"
        ad.mkdir()
        self.assertFalse(b.bug_grabber_installed(ad))
        (ad / "bugsack").mkdir()
        self.assertTrue(b.bug_grabber_installed(ad))
        self.assertFalse(b.bug_grabber_installed(self.root / "nix"))
        self.assertFalse(b.bug_grabber_installed(None))

    def test_multi_account_dedupe_and_case(self):
        wtf = self.root / "wtf"
        _w(wtf / "Account" / "A1" / "SavedVariables" / "!BugGrabber.lua", SAMPLE)
        _w(wtf / "Account" / "A2" / "savedvariables" / "!buggrabber.lua", SAMPLE.replace('"2026/03/02 11:00:00"', '"2026/03/05 11:00:00"'))
        _w(wtf / "Account" / "A3" / "SavedVariables" / "Other.lua", "x = 1")
        errs = b.load_errors(wtf)
        # A2: 1 und 3 identisch zu A1 (message+time), Fehler 2 hat andere Zeit -> 4 Eintraege
        self.assertEqual(len(errs), 4)
        self.assertEqual(b.load_errors(self.root / "nix"), [])
        self.assertEqual(b.load_errors(None), [])
        times = [e.time for e in errs if e.time]
        self.assertEqual(times, sorted(times))


def _err(folder, t, count=1, msg=None):
    return b.BugError(msg or f"Interface\\AddOns\\{folder}\\x.lua:1: fehler", "", t, count, 1, [folder] if folder else [])


class GroupTests(unittest.TestCase):
    def test_group(self):
        hist = [
            {"ts": "2026-03-01T09:00:00", "kind": "Update", "key": "foo", "name": "Foo", "old": "1", "new": "2", "folders": ["Foo"]},
            {"ts": "2026-03-10T09:00:00", "kind": "Update", "key": "foo", "name": "Foo", "old": "2", "new": "3", "folders": ["Foo", "Foo_Opt"]},
            {"ts": "2026-03-20T09:00:00", "kind": "Deinstallation", "key": "foo", "name": "Foo", "old": "3", "new": None},
            {"ts": "2026-03-21T09:00:00", "kind": "Einstellungen", "key": "", "name": "x", "new": None},
            {"ts": "kaputt", "key": "bar", "new": "1"},
        ]
        errs = [
            _err("Foo", datetime(2026, 3, 5), 2),
            _err("foo_opt", datetime(2026, 3, 11), 4),
            _err("Foo", datetime(2026, 3, 12), 1, "Interface\\AddOns\\Foo\\y.lua:1: anders"),
            _err("Bar", datetime(2026, 3, 1), 9),
            _err("Bar", None, 1),
            _err("", datetime(2026, 3, 1), 1, "irgendwas"),
        ]
        m = {"Foo": ("foo", "Foo Addon"), "Foo_Opt": ("foo", "Foo Addon")}
        gs = b.group_errors(errs, m, hist)
        self.assertEqual([g.key for g in gs], ["foo", "folder:Bar", "folder:"])
        foo = gs[0]
        self.assertEqual((foo.name, foo.count, foo.since_update, foo.before_update), ("Foo Addon", 7, 5, 2))
        self.assertEqual(foo.folders, ["Foo", "Foo_Opt"])
        self.assertEqual(foo.last_update["ts"], "2026-03-10T09:00:00")
        self.assertEqual(foo.first, datetime(2026, 3, 5))
        self.assertEqual(foo.last, datetime(2026, 3, 12))
        self.assertEqual(len(foo.samples), 3)
        bar = gs[1]
        self.assertEqual((bar.count, bar.since_update, bar.before_update, bar.last_update), (10, 0, 0, None))
        self.assertEqual(gs[2].name, "Unbekannt")

    def test_sort_and_empty(self):
        self.assertEqual(b.group_errors([], {}, []), [])
        hist = [{"ts": "2026-03-01T00:00:00", "key": "a", "new": "1", "folders": ["A"]}]
        errs = [_err("B", datetime(2026, 3, 2), 50), _err("A", datetime(2026, 3, 2), 1)]
        gs = b.group_errors(errs, {"A": ("a", "A")}, hist)
        self.assertEqual([g.key for g in gs], ["a", "folder:B"])


if __name__ == "__main__":
    unittest.main()
