import unittest

import wfa_selfupdate as su
from helpers import OfflineCase

SUM_A = "a" * 64
SUM_B = "B" * 64


class SelfUpdateTests(OfflineCase):
    def test_vtuple(self):
        self.assertEqual(su._vtuple("v1.2.3"), (1, 2, 3))
        self.assertEqual(su._vtuple("1.2.3-rc1+x"), (1, 2, 3))
        self.assertEqual(su._vtuple("x"), (0,))

    def test_newer(self):
        self.assertTrue(su._newer("0.3.1", "0.3.0"))
        self.assertTrue(su._newer("1.0", "0.9.9"))
        self.assertTrue(su._newer("0.10.0", "0.9.0"))   # numerisch, nicht lexikografisch
        self.assertFalse(su._newer("1.0", "1.0.0"))
        self.assertFalse(su._newer("0.3.0", "0.3.1"))

    def test_parse_sums(self):
        text = f"{SUM_A}  other-file\n{SUM_B} *dist/{su.ASSET_NAME}\nmuell\n"
        self.assertEqual(su._parse_sums(text, su.ASSET_NAME), SUM_B.lower())
        self.assertEqual(su._parse_sums(text, "other-file"), SUM_A)
        self.assertIsNone(su._parse_sums(text, "fehlt"))
        self.assertIsNone(su._parse_sums("abc  " + su.ASSET_NAME, su.ASSET_NAME))   # zu kurze Summe
        self.assertIsNone(su._parse_sums("", su.ASSET_NAME))


if __name__ == "__main__":
    unittest.main()
