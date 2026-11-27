import json
import unittest

import wfa_core as core
from helpers import OfflineCase


class ExportImportTests(OfflineCase):
    def test_short_roundtrip(self):
        data = {"packages": [{"source": "cf:18808"}, {"source": "cf:4646", "channel": "beta"},
                             {"source": "gh:owner/repo", "channel": "alpha"}]}
        text = core.export_text(data)
        self.assertEqual(text, "WFA1 cf:18808 cf:4646@beta gh:owner/repo@alpha")
        self.assertEqual(core.parse_import(text), [
            {"source": "cf:18808"}, {"source": "cf:4646", "channel": "beta"},
            {"source": "gh:owner/repo", "channel": "alpha"}])

    def test_json_roundtrip_via_export_data(self):
        mgr = core.Manager()
        pkgs = [core.Package("a", "Alpha", ["Alpha"], "v1.2.3", cf_mod_id=5, channel="beta"),
                core.Package("b", "Beta", ["Beta"], meta={"gh": "o/r"}),
                core.Package("c", "Cee", ["Cee"])]
        data = mgr.export_data(pkgs)
        self.assertEqual(data["untransferable"], ["Cee"])
        got = core.parse_import(json.dumps(data))
        self.assertEqual([e["source"] for e in got], ["cf:5", "gh:o/r"])
        self.assertEqual(got[0]["channel"], "beta")
        self.assertEqual(got[0]["name"], "Alpha")

    def test_tolerant_input(self):
        got = core.parse_import("```\nwfa1: CF:1, gh:A/b@BETA; cf:1\n```")
        self.assertEqual(got, [{"source": "cf:1"}, {"source": "gh:A/b", "channel": "beta"}])

    def test_duplicates_merge_fields(self):
        text = json.dumps({"packages": [{"source": "cf:1"}, {"source": "cf:1", "name": "N", "channel": "alpha"}]})
        self.assertEqual(core.parse_import(text)[0]["name"], "N")
        self.assertEqual(core.parse_import(text)[0]["channel"], "alpha")

    def test_errors(self):
        bad = ["", "WFA1", "WFA1 quatsch", "WFA9 cf:1", "{kaputt", json.dumps({"x": 1}),
               json.dumps({"format": 99, "packages": []}), json.dumps({"packages": [{"source": "zz:1"}]})]
        for t in bad:
            with self.subTest(t=t), self.assertRaises(core.ApiError):
                core.parse_import(t)
        with self.assertRaises(core.ApiError):
            core.parse_import(None)


class PinTests(OfflineCase):
    def rem(self):
        return core.Remote("r5", "Name r5", "CF", None, 42, "f.zip", file_date="2024-01-02T00:00:00Z")

    def test_pin_record(self):
        rec = core._pin_record("hold", self.rem())
        self.assertEqual(rec["mode"], "hold")
        self.assertEqual(rec["ref"], dict(ident=42, file_date="2024-01-02T00:00:00Z", display="Name r5", version="r5"))
        self.assertRegex(rec["since"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")

    def test_pin_text(self):
        self.assertEqual(core.pin_text(None), "")
        pin = {"mode": "hold", "since": "2024-03-04T10:00:00", "ref": {"version": "Foo_FOREVER_1.2"}}
        self.assertEqual(core.pin_text(pin), "Auf Version 1.2 festgehalten (seit 2024-03-04); Updates werden nicht angeboten.")
        pin["mode"] = "skip"
        self.assertIn("Ausgelassen bis eine Version neuer als 1.2", core.pin_text(pin))
        self.assertIn("neuer als ?", core.pin_text({"mode": "skip"}))


if __name__ == "__main__":
    unittest.main()
