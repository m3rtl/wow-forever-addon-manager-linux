"""Verwaist/veraltet und Konflikte; mod_info aus der API-Antwort."""
import unittest
from datetime import datetime

from helpers import OfflineCase, make_addon
from wfa_base import Package, Remote
import wfa_health as hl
import wfa_sources as src

NOW = datetime(2026, 11, 1)


def pkg(key, folders=None, forever="ok", cf=None, gh=None, date=""):
    p = Package(key=key, name=key, folders=folders or [key], forever=forever, cf_mod_id=cf,
                meta={"gh": gh} if gh else {})
    if date:
        p.remote = Remote("1", "1", "CF", None, 1, "", file_date=date)
    return p


class HealthTests(unittest.TestCase):
    def cfg(self, mods=None, days=180):
        return {"cf_mods": mods or {}, "stale_days": days}

    def test_abandoned(self):
        for st in (7, 8, 9):
            h = hl.assess([pkg("a", cf=1)], self.cfg({"1": {"status": st}}), 16001, NOW)["a"]
            self.assertEqual(h.status, "abandoned")
        h = hl.assess([pkg("a", cf=1)], self.cfg({"1": {"status": 4}}), 16001, NOW)["a"]
        self.assertEqual(h.status, "ok")
        h = hl.assess([pkg("a", cf=1)], self.cfg({"1": {"available": False}}), 16001, NOW)["a"]
        self.assertEqual((h.status, len(h.reasons)), ("abandoned", 1))
        h = hl.assess([pkg("a", gh="o/r")], self.cfg({"gh:o/r": {"archived": True}}), 16001, NOW)["a"]
        self.assertEqual(h.status, "abandoned")

    def test_stale_needs_old_and_outdated_toc(self):
        old = "2025-01-01T00:00:00Z"
        mods = {"1": {"last_file": old}}
        res = hl.assess([pkg("old_ok", cf=1, forever="ok"), pkg("old_out", cf=1, forever="veraltet"),
                         pkg("new_out", cf=2, forever="veraltet")],
                        self.cfg({**mods, "2": {"last_file": "2026-10-01T00:00:00.5Z"}}), 16001, NOW)
        self.assertEqual(res["old_ok"].status, "ok")
        self.assertEqual(res["old_out"].status, "stale")
        self.assertEqual(res["new_out"].status, "ok")
        self.assertEqual(res["old_out"].last_file, datetime(2025, 1, 1))

    def test_fallback_remote_date_and_old_cache(self):
        p = pkg("a", cf=5, forever="veraltet", date="2024-01-01T00:00:00Z")
        h = hl.assess([p], self.cfg({"5": {"name": "x", "slug": "x", "url": ""}}), 16001, NOW)["a"]
        self.assertEqual(h.status, "stale")
        self.assertEqual(hl.assess([pkg("b", forever="veraltet")], self.cfg(), 16001, NOW)["b"].status, "ok")

    def test_mod_info(self):
        m = {"id": 1, "name": "N", "slug": "n", "links": {"websiteUrl": "u"}, "status": 8, "isAvailable": False,
             "latestFiles": [
                 {"fileDate": "2025-05-01T00:00:00Z", "gameVersions": ["1.60.1"]},
                 {"fileDate": "2025-09-01T00:00:00Z", "gameVersions": ["11.0.0"]},
                 {"fileDate": "2025-07-01T00:00:00Z", "gameVersions": [], "sortableGameVersions": [{"gameVersionTypeId": 9}]},
                 {"fileDate": "2026-01-01T00:00:00Z", "gameVersions": ["1.60.1"], "isAvailable": False}]}
        i = src.mod_info(m, 9)
        self.assertEqual((i["status"], i["available"], i["last_file"], i["url"]), (8, False, "2025-07-01T00:00:00Z", "u"))
        j = src.mod_info({"id": 2})
        self.assertEqual(j, {"name": "", "slug": "", "url": "", "last_file": ""})


class ConflictTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.d = self.tmp / "AddOns"
        self.d.mkdir()

    def title(self, name, title):
        make_addon(self.d, name)
        (self.d / name / f"{name}.toc").write_text(f"## Interface: 16001\n## Title: {title}\n{name}.lua\n")

    def test_shared_folder(self):
        self.title("Lib", "Lib")
        res = hl.conflicts([pkg("a", ["A", "Lib"]), pkg("b", ["B", "lib"])], self.d)
        self.assertEqual([(c.kind, c.folders, c.keys) for c in res], [("shared_folder", ["Lib"], ["a", "b"])])

    def test_duplicate_suffix_and_source(self):
        self.title("Foo", "|cffff0000Foo|r")
        self.title("Foo-master", "Foo")
        self.title("Bar", "Same")
        self.title("Baz", "Same")
        self.title("Qux", "Different")
        pk = [pkg("p1", ["Foo"]), pkg("p2", ["Foo-master"]), pkg("p3", ["Bar"], cf=7), pkg("p4", ["Baz"], cf=7),
              pkg("p5", ["Qux"], cf=7)]
        res = hl.conflicts(pk, self.d)
        got = sorted((c.kind, tuple(c.folders)) for c in res)
        self.assertEqual(got, [("duplicate", ("Bar", "Baz")), ("duplicate", ("Foo", "Foo-master"))])

    def test_same_title_unrelated_no_conflict(self):
        self.title("Alpha", "Same")
        self.title("Beta", "Same")
        self.assertEqual(hl.conflicts([pkg("a", ["Alpha"]), pkg("b", ["Beta"])], self.d), [])


if __name__ == "__main__":
    unittest.main()
