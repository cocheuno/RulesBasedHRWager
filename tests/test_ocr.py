"""Payout-page parsing on real OCR rows (tests/fixtures_ocr_rows.json, read from Del Mar 2026-11-06 screenshots
by RapidOCR).  No OCR engine is needed for these; the engine itself is exercised only if installed."""
from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from handicapper.ocr import parse_payout_rows   # noqa: E402

ROSTER = {
    1: {"1": "Sunny Creed", "2": "La Cantina Rossa", "3": "Howmanymoretimes", "4": "Debby's Gal", "5": "Princess Breanna", "6": "Hard Hearted"},
    6: {"1": "Tailgunner Joe", "2": "Jordi Bear", "8": "Green Carrera", "9": "Deucari"},
    8: {"1": "Eugene Sledge", "4": "Ottis Betts", "7": "Allequin Summer", "8": "Cal's Goal", "11": "Scatalotadingdong"},
}


def rows_for(rn):
    fx = json.load(open(os.path.join(HERE, "fixtures_ocr_rows.json"), encoding="utf-8"))
    return [(y, [tuple(t) for t in toks]) for y, toks in fx[str(rn)]]


class TestParse(unittest.TestCase):
    def test_race1(self):
        r = parse_payout_rows(rows_for(1), 1, ROSTER[1])
        self.assertEqual(r["finish"], ["1", "6", "4", "3"])
        self.assertEqual(r["win"], 5.20)
        self.assertEqual(r["place"], {"1": 3.40, "6": 9.20})
        self.assertEqual(r["show"], {"1": 2.10, "6": 3.20, "4": 2.10})
        self.assertEqual([(e["type"], e["base"], e["combo"], e["payout"]) for e in r["exotics"]],
                         [("EXACTA", 1.0, "1/6", 17.30), ("QUINELLA", 2.0, "1/6", 31.60), ("TRIFECTA", 0.5, "1/6/4", 13.50), ("SUPERFECTA", 0.1, "1/6/4/3", 12.46)])
        self.assertEqual(r["ocr"]["names"], ["Sunny Creed", "Hard Hearted", "Debby's Gal"])
        self.assertEqual(r["ocr"]["name_pgms"], ["1", "6", "4"])
        self.assertEqual(r["ocr"]["warnings"], [])

    def test_race6_double_and_pick3(self):
        r = parse_payout_rows(rows_for(6), 6, ROSTER[6])
        self.assertEqual(r["finish"], ["8", "9", "2", "1"])
        types = [e["type"] for e in r["exotics"]]
        self.assertEqual(types, ["EXACTA", "QUINELLA", "TRIFECTA", "SUPERFECTA", "DOUBLE", "PICK3"])
        self.assertEqual(next(e for e in r["exotics"] if e["type"] == "PICK3"), {"type": "PICK3", "base": 0.5, "combo": "7/2/8", "payout": 25.10})
        self.assertEqual(r["ocr"]["names"][0], "Green Carrera")
        self.assertEqual(r["ocr"]["warnings"], [])

    def test_race8_long_menu_and_consolations(self):
        r = parse_payout_rows(rows_for(8), 8, ROSTER[8])
        self.assertEqual(r["finish"], ["4", "8", "1", "7", "11"])
        self.assertEqual(r["win"], 14.00)
        types = [e["type"] for e in r["exotics"]]
        self.assertEqual(types, ["EXACTA", "QUINELLA", "TRIFECTA", "SUPERFECTA", "SUPERHIGHFIVE", "DOUBLE", "PICK3", "PICK4", "PICK5", "PICK6"])
        self.assertEqual(next(e for e in r["exotics"] if e["type"] == "PICK6")["payout"], 32455.00, "the consolation line is not taken")
        self.assertEqual(next(e for e in r["exotics"] if e["type"] == "SUPERHIGHFIVE")["payout"], 6254.30)
        self.assertTrue(any("PICK8" in w for w in r["ocr"]["warnings"]), "the wrapped Pick 8 line is reported, not guessed")
        self.assertEqual(r["ocr"]["name_pgms"], ["4", "8", "1"])

    def test_name_disagreement_is_a_warning(self):
        bad = dict(ROSTER[1]); bad["1"], bad["6"] = "Hard Hearted", "Sunny Creed"   # roster swapped on purpose
        r = parse_payout_rows(rows_for(1), 1, bad)
        self.assertEqual(r["finish"], ["1", "6", "4", "3"], "combos still decide the order")
        self.assertTrue(any("combos say #1" in w for w in r["ocr"]["warnings"]))

    def test_without_roster(self):
        r = parse_payout_rows(rows_for(6), 6, None)
        self.assertEqual(r["finish"], ["8", "9", "2", "1"])
        self.assertEqual(r["ocr"]["name_pgms"], [])


class TestEngine(unittest.TestCase):
    def test_engine_if_installed(self):
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except ImportError:
            self.skipTest("rapidocr_onnxruntime not installed")
        from handicapper.ocr import ocr_rows
        img = os.path.join(HERE, "fixtures", "r1.png")
        if not os.path.exists(img):
            self.skipTest("no fixture image")
        rows = ocr_rows(img)
        self.assertTrue(any("EXACTA" in t for y, toks in rows for x, t, c in toks))


if __name__ == "__main__":
    unittest.main()
