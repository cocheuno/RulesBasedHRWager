"""TimeformUS PP reader on an anonymised text-layer fixture; merge under the card's `timeform` namespace."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from timeform_pp.reader import merge_timeform, parse_lines, rank_by_top_fig   # noqa: E402

FIX = os.path.join(HERE, "fixtures", "timeform_sample.txt")


def load():
    with open(FIX, encoding="utf-8") as fh:
        return parse_lines(fh.read().splitlines(), source="sample.pdf")


class TestReader(unittest.TestCase):
    def setUp(self):
        self.doc = load()
        self.r1, self.r2 = self.doc["races"]
        self.h = {h["pgm"]: h for h in self.r1["horses"]}

    def test_identity_and_races(self):
        self.assertEqual((self.doc["track"], self.doc["date"]), ("SAMPLE PARK", "2026-11-15"))
        self.assertEqual([r["race_no"] for r in self.doc["races"]], [1, 2])
        self.assertEqual((self.r1["post_time"], self.r1["distance_text"], self.r1["surface"], self.r1["race_type"]), ("12:40 PM", "7 F", "Dirt", "Maiden"))
        self.assertEqual((self.r2["post_time"], self.r2["distance_text"], self.r2["surface"]), ("1:12 PM", "1 1/16 M", "Turf"))
        self.assertEqual([h["pgm"] for h in self.r1["horses"]], ["1", "1A", "2", "3", "4"])

    def test_three_digit_top_fig_is_read_through_the_garble(self):
        self.assertEqual(self.h["3"]["top_fig"], 102)          # printed as "To 1 p 0 2 Fig"
        self.assertEqual(self.h["1"]["top_fig"], 49)
        self.assertEqual(self.h["4"]["top_fig"], 86)
        self.assertEqual(self.h["3"]["lines"][1]["speed_fig"], 102)

    def test_first_time_starter_has_no_figure_and_no_lines(self):
        d = self.h["2"]
        self.assertTrue(d["debut"])
        self.assertIsNone(d["top_fig"])
        self.assertEqual(d["lines"], [])
        self.assertEqual((d["ml"], d["early"], d["late"]), ("8-1", 70, 50))
        self.assertIn("Nov8", d["works_text"])

    def test_program_letter_is_kept(self):
        self.assertEqual(self.h["1A"]["name"], "Harbor Light")
        self.assertEqual(self.h["1A"]["top_fig"], 54)
        self.assertEqual(rank_by_top_fig(self.r1["horses"]), {"1": 4, "1A": 3, "2": None, "3": 1, "4": 2})

    def test_running_style_with_and_without_the_style_word(self):
        self.assertEqual((self.h["1"]["style"], self.h["1"]["early"], self.h["1"]["late"]), (None, 60, 43))
        self.assertEqual((self.h["3"]["style"], self.h["3"]["early"], self.h["3"]["late"]), ("Midpack", 58, 70))
        self.assertEqual((self.h["1"]["ml"], self.h["1"]["weight"]), ("30-1", 124))

    def test_running_lines_carry_their_own_dates_and_fields(self):
        ln = self.h["4"]["lines"]
        self.assertEqual([x["date"] for x in ln], ["2026-10-10", "2026-07-19", "2026-06-21"])
        self.assertEqual([x["speed_fig"] for x in ln], [74, 86, 83])
        self.assertEqual(ln[0]["figs"], [None, 84, 83, 79, 71])
        self.assertEqual((ln[0]["condition"], ln[0]["odds"], ln[0]["post"], ln[0]["weight"], ln[0]["field_size"]), ("Fast", "3-1", "F8", 123, 9))
        self.assertEqual((ln[2]["condition"], ln[2]["weight"], ln[2]["equipment"]), ("Wet Fast", 118, "LBF"))
        self.assertEqual(ln[1]["figs"], [81, 80, 90, 88, 85])
        self.assertEqual((ln[1]["surface"], ln[1]["distance_text"], ln[1]["track"], ln[1]["race_rating"]), ("Turf", "1 1/16 M", "SAR", 93))
        self.assertTrue(ln[0]["comment"].startswith("bumped start"))
        # the year steps back across a December -> January boundary read newest first
        self.assertEqual(self.h["3"]["lines"][0]["bias_note"], "Slight")
        self.assertEqual(self.h["3"]["notes"], ["CLAIMED FROM SAMPLE STABLE, TRAINER - SAMPLE TRAINER (68) FOR $35,000"])

    def test_power_picks_and_pace_projector(self):
        self.assertEqual(self.r1["power_picks"], ["3", "4", "1"])
        self.assertEqual(self.r1["pace_projector"], ["1", "1A", "2", "3", "4"])
        self.assertEqual(self.r1["pace_projector_basis"], "text-layer")
        self.assertEqual(self.r2["power_picks"], ["2", "1"])

    def test_year_boundary(self):
        lines = ["X PARK 1/10/2027", "RACE X", "1 3Õ 6 F", "1/10/2027 1:00 PM 70 Claiming Dirt",
                 "1 Year Hopper Colt | Age 4 | Mar | KY-bred Top 70 Fig",
                 "ML: 3-1 | | WT: 120lbs (S) 2026 2 0 0 0 $0 70",
                 "Running Style: 60 Midpack 60 Owner: O",
                 "20 Days AQU 70 3Õ Dirt 6 F A B P 1 2 2 2 2 1 70 1 Year Hopper 1 2 Other 1 3 Third 1",
                 "Dec 21 $20K Claiming Fast 7 120 |L | 3-1 F 1 70 70 70 70 clear",
                 "30 Days AQU 70 3Õ Dirt 6 F A B P 1 2 2 2 2 2 65 1 Someone 1 2 Year Hopper 1 3 Third 1",
                 "Nov 21 $20K Claiming Fast 7 120 |L | 3-1 F 1 65 65 65 65 second"]
        d = parse_lines(lines)
        self.assertEqual([x["date"] for x in d["races"][0]["horses"][0]["lines"]], ["2026-12-21", "2026-11-21"])

    def test_trimmed_file_without_race_headers_splits_on_program_restart(self):
        lines = ["1 A Colt | Age 3 | Mar | KY-bred Top 70 Fig", "ML: 3-1 | | WT: 120lbs", "2 B Colt | Age 3 | Mar | KY-bred Top 60 Fig",
                 "1 C Colt | Age 3 | Mar | KY-bred Top 50 Fig"]
        d = parse_lines(lines)
        self.assertEqual([[h["pgm"] for h in r["horses"]] for r in d["races"]], [["1", "2"], ["1"]])
        self.assertEqual([r["race_no"] for r in d["races"]], [1, 2])


class TestMerge(unittest.TestCase):
    def card(self):
        return {"track": "Sample Park", "track_code": "SMP", "date": "2026-11-15", "races": [
            {"race_no": 1, "horses": [{"pgm": "1", "name": "Quiet Harbor"}, {"pgm": "1A", "name": "Harbor Light"}, {"pgm": "2", "name": "Copper Lantern"},
                                      {"pgm": "3", "name": "Night Ledger"}, {"pgm": "4", "name": "Paper Moon"}, {"pgm": "5", "name": "Late Entry"}]},
            {"race_no": 2, "horses": [{"pgm": "1", "name": "Sable Coast"}, {"pgm": "2", "name": "Different Horse"}]},
            {"race_no": 3, "horses": [{"pgm": "1", "name": "Nobody Home"}]}]}

    def test_merge_under_its_own_namespace(self):
        card = self.card()
        notes = merge_timeform(card, load())
        r1 = card["races"][0]
        self.assertEqual(r1["timeform"]["rank"]["3"], 1)
        self.assertEqual(r1["timeform"]["power_picks"], ["3", "4", "1"])
        self.assertEqual(r1["horses"][3]["timeform"]["top_fig"], 102)
        self.assertEqual(r1["horses"][3]["timeform"]["rank"], 1)
        self.assertEqual(r1["horses"][3]["timeform"]["source"], "timeformus")
        self.assertTrue(r1["horses"][2]["timeform"]["debut"])
        self.assertIsNone(r1["horses"][5]["timeform"])                     # not in the Timeform file: no Brisnet value substituted
        self.assertIsNone(card["races"][1]["horses"][1]["timeform"])        # same program number, different name: not merged
        self.assertIsNone(card["races"][2]["timeform"])                     # partial file
        self.assertTrue(any("R3: not in the Timeform file" in n for n in notes))
        self.assertTrue(any("Different Horse" in n for n in notes))
        self.assertNotIn("speed", r1["horses"][3]["timeform"])             # no Brisnet keys under the Timeform namespace

    def test_wrong_date_is_not_merged(self):
        card = self.card(); card["date"] = "2026-11-14"
        notes = merge_timeform(card, load())
        self.assertNotIn("timeform", card["races"][0])
        self.assertTrue(notes and "not merged" in notes[0])


if __name__ == "__main__":
    unittest.main()
