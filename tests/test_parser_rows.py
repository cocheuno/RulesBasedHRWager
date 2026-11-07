"""Parser regressions found on the Belmont 2026-11-06 card: turf sprints headed "(t)", a debut runner whose
stats block starts with a '+' flag and whose workouts sit above the (absent) past-performance table."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from brisnet_pp.parser import BrisnetPPParser, Row   # noqa: E402
from brisnet_pp.symbols import SYM_AW                # noqa: E402


def row(top, tokens, page=1):
    """Build a Row from (x0, text) tokens; characters are laid out at ~4 pt each."""
    chars = []
    for x0, text in tokens:
        x = float(x0)
        for ch in text:
            chars.append({"text": ch, "x0": x, "x1": x + 3.6, "top": float(top), "fontname": "PP2A"})
            x += 3.8
        chars.append({"text": " ", "x0": x, "x1": x + 1, "top": float(top), "fontname": "PP2A"})
    return Row(top=float(top), chars=chars, page=page)


class TestRaceHeader(unittest.TestCase):
    def test_lower_case_turf_marker(self):
        p = BrisnetPPParser.__new__(BrisnetPPParser)
        race = {"header_text": "MC 50000 6 Furlongs (t) 2yo Friday, November 06, 2026"}
        p._derive_race_fields(race)
        self.assertEqual((race["class_text"], race["distance_furlongs"], race["surface"], race["class_code"]), ("MC 50000", 6.0, "turf", "MCL"))
        race = {"header_text": "Moc 75000 6½ Furlongs (t) 2yo Fillies Friday, November 06, 2026"}
        p._derive_race_fields(race)
        self.assertEqual((race["distance_furlongs"], race["surface"]), (6.5, "turf"))
        race = {"header_text": "OC 80000n1x 1 Mile (T) 3&up Friday, November 06, 2026"}
        p._derive_race_fields(race)
        self.assertEqual((race["distance_furlongs"], race["surface"]), (8.0, "turf"))
        race = {"header_text": "Clm 12500n2L 5½ Furlongs 3&up, F & M Friday, November 06, 2026"}
        p._derive_race_fields(race)
        self.assertEqual((race["class_text"], race["distance_furlongs"], race["surface"], race["sex_text"]), ("Clm 12500n2L", 5.5, "dirt", "F & M"))

    def test_all_weather_and_mile_seventy(self):
        p = BrisnetPPParser.__new__(BrisnetPPParser)
        race = {"header_text": f"Hcp 60000 {SYM_AW} 1m70yds 3&up, F & M Saturday, November 07, 2026"}
        p._derive_race_fields(race)
        self.assertEqual((race["class_text"], race["distance_furlongs"], race["surface"], race["is_route"], race["class_code"]), ("Hcp 60000", 8.32, "aw", True, "HCP"))
        race = {"header_text": f"Mdn 50k {SYM_AW} 5½ Furlongs 2yo Fillies Saturday, November 07, 2026"}
        p._derive_race_fields(race)
        self.assertEqual((race["distance_furlongs"], race["surface"], race["sex_text"]), (5.5, "aw", "Fillies"))
        race = {"header_text": "Clm 10000 1 Mile 70 Yards 3&up Friday, November 06, 2026"}
        p._derive_race_fields(race)
        self.assertEqual((race["distance_furlongs"], race["surface"]), (8.32, "dirt"))


class TestDebutRunnerBlock(unittest.TestCase):
    def test_stats_with_plus_flag_and_workouts_without_pp_table(self):
        p = BrisnetPPParser.__new__(BrisnetPPParser)
        p.card = {"date": "2026-11-06"}
        p.warnings = []
        block = [
            row(183, [(5, "1"), (40, "Bletchley (NA 0) B. c. 2 (Apr) KEESEP 2025 $1550k"), (392, "Life: 0 0 - 0 - 0 $0"), (487, "Fst (114) 0 0 - 0 - 0 $0")]),
            row(200, [(5, "8/5"), (36, "Own: Magnier Mrs John")]),
            row(206, [(200, "Trnr: Brown Chad C (127 31-23-20 24%)")]),
            row(210, [(5, "PRAT FLAVIEN (131 30-23-21 23%)")]),
            row(220, [(7, "+2026 1178 25% 57% -0.27"), (192, "+2026 794 23% 59% -0.48")]),
            row(228, [(7, "+JKYw/NA types 404 19% 51% -0.37"), (192, "+1st time str 634 18% 48% -0.61")]),
            row(243, [(7, "+JKYw/ Routes 312 30% 64% +0.02"), (192, "+Debut MdnSpWt 597 18% 48% -0.59")]),
            row(289, [(5, "31Oct Bel 4f ft :49 B 18/29 24Oct Bel 4f ft :48 B 26/78 18Oct Bel 4f ft :48 B 24/71")]),
            row(297, [(5, "29Aug Bel 4f ft :48 B 15/93 22Aug Bel 4f ft :48 Bg 23/107")]),
        ]
        h = p._parse_horse_block(block, {"race_no": 1})
        self.assertEqual(h["name"], "Bletchley")
        self.assertEqual(h["pp"], [])
        self.assertEqual(len(h["workouts"]), 5, "workouts of a debut runner are read from the head block")
        self.assertEqual(h["workouts"][0]["date"], "31Oct")
        cats = [t["category"] for t in h["trainer_stats"]]
        self.assertIn("2026", cats)
        self.assertIn("1st time str", cats)
        self.assertTrue(all(t["flag"] for t in h["trainer_stats"]))
        self.assertEqual(h["trainer_stats"][0]["win_pct"], 23)
        self.assertEqual(h["jockey_stats"][0]["category"], "2026")
        self.assertTrue(h["jockey_stats"][0]["flag"])


if __name__ == "__main__":
    unittest.main()
