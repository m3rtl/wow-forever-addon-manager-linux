import unittest

import wfa_core as core
from helpers import OfflineCase


class VersionTests(OfflineCase):
    def test_short_version(self):
        self.assertEqual(core.short_version("Addon_FOREVER_2.3.4"), "2.3.4")
        self.assertEqual(core.short_version("r123"), "r123")
        self.assertEqual(core.short_version("16001 1.60.1 3.2"), "3.2")   # Interface/Spielversion uebersprungen
        self.assertEqual(core.short_version("  nix "), "nix")
        self.assertEqual(core.short_version(None), "")

    def test_display_version(self):
        self.assertEqual(core.display_version("Name_FOREVER_v1.2.3"), "v1.2.3")
        self.assertEqual(core.display_version("1.2.3"), "1.2.3")
        self.assertEqual(core.display_version(None), "")

    def test_norm(self):
        self.assertEqual(core.norm("1.2.0"), ("d", (1, 2)))
        self.assertEqual(core.norm("r12.3"), ("r", (12, 3)))
        self.assertIsNone(core.norm("abc"))
        self.assertIsNone(core.norm(None))

    def test_compare(self):
        c = core.compare
        self.assertEqual(c("1.0", "1.1"), core.UPDATE)
        self.assertEqual(c("1.0.0", "1.0"), core.CURRENT)
        self.assertEqual(c("2.0", "1.9"), core.NEWER)
        self.assertEqual(c("r10", "r9"), core.NEWER)
        self.assertEqual(c("r1", "r2"), core.UPDATE)
        self.assertEqual(c("r1", "1.2"), core.UNKNOWN)   # verschiedene Schemata
        self.assertEqual(c("abc", "abc"), core.CURRENT)
        self.assertEqual(c("abc", "def"), core.UNKNOWN)
        self.assertEqual(c(None, "1.0"), core.UNKNOWN)


class MiscTests(OfflineCase):
    def test_network_is_blocked(self):
        import socket
        with self.assertRaises(RuntimeError):
            socket.create_connection(("127.0.0.1", 9))
        with self.assertRaises(RuntimeError):
            socket.socket().connect(("127.0.0.1", 9))
        with self.assertRaises(RuntimeError):
            core.http_json("https://example.invalid/")

    def test_channel_types(self):
        self.assertEqual(core.channel_types("release"), {1})
        self.assertEqual(core.channel_types("beta"), {1, 2})
        self.assertEqual(core.channel_types("alpha"), {1, 2, 3})
        self.assertEqual(core.channel_types(True), {1, 2})
        self.assertEqual(core.channel_types(None), {1})
        self.assertEqual(core.channel_types({3}), {3})

    def test_mask(self):
        self.assertEqual(core.mask(""), "(leer)")
        self.assertEqual(core.mask("abcdefgh"), "****efgh")
        self.assertEqual(core.mask("abc"), "abc")

    def test_fmt_size(self):
        self.assertEqual(core.fmt_size(0), "0 B")
        self.assertEqual(core.fmt_size(None), "0 B")
        self.assertEqual(core.fmt_size(1536), "1,5 KB")
        self.assertEqual(core.fmt_size(5 * 1024 * 1024), "5,0 MB")

    def test_parse_github(self):
        self.assertEqual(core.parse_github("gh:owner/repo"), "owner/repo")
        self.assertEqual(core.parse_github("https://github.com/o/r.git"), "o/r")
        self.assertEqual(core.parse_github(" https://github.com/o/r/releases/tag/v1 "), "o/r")
        self.assertIsNone(core.parse_github("https://example.com/o/r"))
        self.assertIsNone(core.parse_github("owner"))

    def test_is_zip_url(self):
        self.assertTrue(core.is_zip_url("https://x.org/a/B.ZIP"))
        self.assertTrue(core.is_zip_url("http://x.org/a.zip?x=1"))
        self.assertFalse(core.is_zip_url("https://x.org/a.zip.html"))
        self.assertFalse(core.is_zip_url("ftp://x.org/a.zip"))
        self.assertFalse(core.is_zip_url("a.zip"))


if __name__ == "__main__":
    unittest.main()
