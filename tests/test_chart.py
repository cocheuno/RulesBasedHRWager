"""Equibase/Brisnet result chart reading, on the row fixture taken from the Belmont 2026-11-06 race 1 chart
(runner table, off/time, mutuels and exotics; the footnote prose is not in the fixture)."""
from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from brisnet_pp.chart import chart_to_result, parse_chart_rows, rows_from_fixture, split_comments   # noqa: E402
from ocr_results import race_no_of   # noqa: E402


class TestChart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows = rows_from_fixture(json.load(open(os.path.join(HERE, "fixtures_chart_rows.json"), encoding="utf-8")))
        cls.c = parse_chart_rows(rows, 1)
        cls.r = chart_to_result(cls.c)

    def test_header(self):
        c = self.c
        self.assertEqual((c["race_no"], c["track"], c["date_text"]), (1, "Belmont Park", "November 6th, 2026"))
        self.assertEqual((c["distance_text"], c["class_text"], c["purse"], c["weather"]), ("1 Mile", "Maiden Special Weight", 100000, "Showery 65"))
        self.assertEqual((c["track_condition"], c["surface"], c["off_at"]), ("SLOPPY (sealed)", "DIRT", "12:42"))
        self.assertEqual(c["times"], [23.14, 45.72, 69.92, 82.21, 95.12])
        self.assertTrue(c["official"])

    def test_finish_odds_and_calls(self):
        r = self.r
        self.assertEqual(r["finish"], ["1", "2", "6", "5", "4", "3"])
        self.assertEqual(r["final_odds"], {"1": 1.82, "2": 4.12, "6": 16.85, "5": 4.91, "4": 24.38, "3": 1.65})
        by = {x["pgm"]: x for x in r["runners"]}
        self.assertEqual((by["1"]["finish"], by["1"]["margin"], by["1"]["beaten"]), (1, 7.75, 0.0))
        self.assertEqual(by["2"]["beaten"], 7.75)
        self.assertEqual(by["6"]["equipment"], "b")
        self.assertEqual((by["1"]["weight"], by["1"]["post"], by["1"]["jockey"]), (123, 1, "Prat F"))
        self.assertEqual([(cl["call"], cl["pos"]) for cl in by["6"]["calls"]], [("¼", 1), ("½", 1), ("¾", 1), ("Str", 2)])
        self.assertEqual(by["1"]["calls"][0]["lengths"], 2.25)

    def test_mutuels_and_exotics(self):
        r = self.r
        self.assertEqual(r["win"], 5.64)
        self.assertEqual(r["place"], {"1": 3.82, "2": 4.04})
        self.assertEqual(r["show"], {"1": 2.84, "2": 3.32, "6": 6.74})
        self.assertEqual(sorted((e["type"], e["base"], e["combo"], e["payout"]) for e in r["exotics"]),
                         [("EXACTA", 1.0, "1/2", 10.82), ("SUPERFECTA", 0.1, "1/2/6/5", 22.85), ("TRIFECTA", 0.5, "1/2/6", 38.42)])

    def test_comment_split(self):
        prose = ("ALPHA chased the pace and bumped BETA at the start, then drew clear. BETA got bumped by ALPHA and tired. "
                 "GAMMA DELTA broke slowly; DELTA never threatened.")
        out = split_comments(prose, [("Alpha", "1"), ("Beta", "2"), ("Gamma Delta", "3"), ("Delta", "4")])
        self.assertTrue(out["1"].startswith("ALPHA chased") and out["1"].endswith("drew clear."))
        self.assertTrue(out["2"].startswith("BETA got bumped"))
        self.assertTrue(out["3"].startswith("GAMMA DELTA broke"))
        self.assertTrue(out["4"].startswith("DELTA never"))

    def test_chart_replaces_typed_entry(self):
        import json as _json, os as _os, shutil, tempfile
        import ocr_results
        tmp = tempfile.mkdtemp()
        try:
            res = _os.path.join(tmp, "x.results.json")
            _json.dump({"track": "Belmont Park", "races": [{"race_no": 1, "finish": ["1", "2"], "win": 5.0}]}, open(res, "w"))
            open(_os.path.join(tmp, "20261106BELUSA1.pdf"), "wb").write(b"%PDF")
            chart = chart_to_result(parse_chart_rows(rows_from_fixture(_json.load(open(_os.path.join(HERE, "fixtures_chart_rows.json")))), 1))
            orig = ocr_results.parse_chart
            ocr_results.parse_chart = lambda path: [chart]
            try:
                out = ocr_results.ocr_folder(tmp, res)
                data = _json.load(open(res))
                self.assertEqual(len(out["races"]), 1, "the typed entry is replaced by the chart")
                self.assertEqual(data["races"][0]["finish"], ["1", "2", "6", "5", "4", "3"])
                self.assertEqual(data["races"][0]["source"], "chart")
                out2 = ocr_results.ocr_folder(tmp, res)
                self.assertEqual(out2["races"], [], "a chart entry is not re-read without --force")
            finally:
                ocr_results.parse_chart = orig
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_race_no_from_file_names(self):
        self.assertEqual(race_no_of("x/20261106BELUSA1.pdf"), 1)
        self.assertEqual(race_no_of("x/20261106GPXUSA11.pdf"), 11)
        self.assertEqual(race_no_of("x/r7.png"), 7)
        self.assertEqual(race_no_of("x/r7.pdf"), 7)
        self.assertIsNone(race_no_of("x/notes.pdf"))


if __name__ == "__main__":
    unittest.main()
