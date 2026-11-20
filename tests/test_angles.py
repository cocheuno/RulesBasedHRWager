"""Measured angles (no points): past-race track condition on an off surface today, and Brisnet's race-type statistics."""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ["RACEDESK_WEATHER"] = "off"; os.environ["RACEDESK_TOTE"] = "off"

from synthetic_card import build_card                                       # noqa: E402
from handicapper import angles as AN                                         # noqa: E402
from handicapper.engine import load_config, score_card                       # noqa: E402
from handicapper.results import backtest                                     # noqa: E402

CFG_PATH = os.path.join(ROOT, "rules_config.json")


def line(cond, pos, surface="dirt"):
    return {"track_condition": cond, "finish_pos": pos, "surface": surface, "dnf": False}


class TestCodes(unittest.TestCase):
    def test_codes(self):
        self.assertEqual([AN.norm_code(c) for c in ("SYS", "my", "gd", "", None)], ["sy", "my", "gd", None, None])
        self.assertEqual([AN.code_from_text(t) for t in ("MUDDY (sealed)", "Fast", "Wet Fast", "Firm", "Yielding", "sys", None)],
                         ["my", "ft", "wf", "fm", "yl", "sy", None])
        self.assertTrue(AN.is_off("my", "dirt")); self.assertFalse(AN.is_off("ft", "dirt"))
        self.assertTrue(AN.is_off("yl", "turf")); self.assertFalse(AN.is_off("fm", "turf")); self.assertTrue(AN.is_off("gd", "turf"))
        self.assertEqual(AN.line_surface({"track_condition": "fm", "surface": "dirt"}), "turf")   # a turf condition marks a turf line


class TestConditionAngles(unittest.TestCase):
    def test_labels(self):
        h = {"pp": [line("ft", 1), line("sy", 1), line("my", 5)], "pedigree_stats": {"sire": {"mud_pct": 21}}, "pedigree_ratings": {"off": "112*"}}
        labs = [a["label"] for a in AN.condition_angles(h, "dirt", "sy")]
        self.assertEqual(labs, ["Off dirt today: won on an off dirt before", "Off dirt today: sire's mud-winner rate 18% or more",
                                "Off dirt today: Brisnet off-track pedigree rating 110 or more"])
        self.assertEqual(AN.condition_angles(h, "dirt", "ft"), [])                            # fast today: no condition angles
        self.assertEqual(AN.condition_angles({"pp": [line("my", 2)]}, "dirt", "my")[0]["label"], "Off dirt today: in the money on an off dirt, no win")
        self.assertEqual(AN.condition_angles({"pp": [line("my", 6), line("sy", 7)]}, "dirt", "my")[0]["label"], "Off dirt today: out of the money in 2 or more off-dirt starts")
        self.assertEqual(AN.condition_angles({"pp": [line("my", 6)]}, "dirt", "my")[0]["label"], "Off dirt today: one off-dirt start, out of the money")
        self.assertEqual(AN.condition_angles({"pp": [line("ft", 1)]}, "dirt", "my")[0]["label"], "Off dirt today: no start on an off dirt")
        turf = AN.condition_angles({"pp": [line("yl", 1, "turf"), line("sy", 1)]}, "turf", "yl")
        self.assertEqual([a["label"] for a in turf], ["Off turf today: won on an off turf before"])   # the wet-dirt win does not count on turf


class TestRaceType(unittest.TestCase):
    def test_labels(self):
        race = {"racetype_stats": {"fav_win_pct": 42, "pct_winners_gt_10_1": 16}}
        live = [{"pgm": "1", "ml_decimal": 1.5}, {"pgm": "2", "ml_decimal": 3.0}, {"pgm": "3", "ml_decimal": 12.0}, {"pgm": "4", "ml_decimal": None}]
        out = AN.racetype_angles(race, live)
        self.assertEqual(out["1"][0]["label"], "Morning-line favourite: favourites win 40% or more of this race type")
        self.assertEqual(out["3"][0]["label"], "10-1 or longer: winners at 10-1 or more are 15% or more of this race type")
        self.assertNotIn("2", out); self.assertNotIn("4", out)
        tie = AN.racetype_angles(race, [{"pgm": "1", "ml_decimal": 2.0}, {"pgm": "2", "ml_decimal": 2.0}])
        self.assertFalse(tie)                                                              # co-favourites: no favourite angle
        self.assertEqual(AN.racetype_angles({}, live), {})


class TestEngineAndBacktest(unittest.TestCase):
    def card(self):
        c = build_card()
        r1 = c["races"][0]
        r1["racetype_stats"] = {"fav_win_pct": 25, "pct_winners_gt_10_1": 5}
        r1["track_condition_morning"] = "Sloppy (sealed)"
        r1["horses"][0]["pp"][0]["track_condition"] = "sy"; r1["horses"][0]["pp"][0]["finish_pos"] = 1
        return c

    def test_no_score_change_and_backtest_rows(self):
        cfg = load_config(CFG_PATH, "DMR")
        from unittest import mock
        with mock.patch.object(AN, "race_angles", lambda race, rows, tc: {}):               # the same card, angles switched off
            plain = score_card(self.card(), cfg, multirace=False)
        res = score_card(self.card(), cfg, multirace=False)
        for a, b in zip(plain["races"], res["races"]):
            self.assertEqual(a["picks"], b["picks"]); self.assertEqual([s["score"] for s in a["sheets"]], [s["score"] for s in b["sheets"]])
        r1 = res["races"][0]
        s1 = next(s for s in r1["sheets"] if s["pgm"] == "1")
        self.assertIn({"kind": "track condition", "label": "Off dirt today: won on an off dirt before"}, s1["angles"])
        self.assertIn({"kind": "race type", "label": "Morning-line favourite: favourites win under 30% of this race type"}, s1["angles"])
        self.assertTrue(all(s.get("angles") == [] for s in res["races"][1]["sheets"]))       # fast, no race-type stats
        bt = backtest(res, {"races": [{"race_no": 1, "finish": ["1", "2", "6"], "win": 5.2}]})
        by = {(a["kind"], a["label"]): a for a in bt["angles"]}
        self.assertEqual(by[("track condition", "Off dirt today: won on an off dirt before")]["won"], 1)

    def test_report_from_card_files(self):
        from handicapper.pipeline import run_card
        from handicapper.snapshot import write_snapshot
        tmp = tempfile.mkdtemp()
        try:
            card = self.card()
            del card["races"][0]["track_condition_morning"]                                 # no morning condition: the chart's is used
            os.makedirs(os.path.join(tmp, "data", "out")); os.makedirs(os.path.join(tmp, "results"))
            res = run_card(copy.deepcopy(card), config_path=CFG_PATH, multirace=False)["result"]
            for r in res["races"]:
                for s in r["sheets"]:
                    s.pop("angles", None)                                                     # an older run, made before the angles existed
            write_snapshot(os.path.join(tmp, "data", "out"), "synth", res, "pre-race")
            for name, obj in (("synth.picks.json", res), ("synth.card.json", card)):
                with open(os.path.join(tmp, "data", "out", name), "w", encoding="utf-8") as fh:
                    json.dump(obj, fh, default=str)
            with open(os.path.join(tmp, "results", "synth.results.json"), "w", encoding="utf-8") as fh:
                json.dump({"track": "Del Mar", "date": card["date"], "races": [{"race_no": 1, "finish": ["1", "2", "6"], "win": 5.2, "track_condition": "SLOPPY (sealed)"}]}, fh)
            rep = AN.angle_report(tmp, load_config(CFG_PATH))
            self.assertEqual((rep["races"]["total"], rep["races"]["with_card"], rep["races"]["off_condition"]), (1, 1, 1))
            self.assertEqual(rep["races"]["basis"], {"chart (post time)": 1})
            row = next(d for d in rep["rows"] if d["label"] == "Off dirt today: won on an off dirt before")
            self.assertEqual((row["fired"], row["won"], row["roi"]), (1, 1, 1.6))
            self.assertIn("| track condition | Off dirt today: won on an off dirt before | 1 | 1 |", AN.format_angle_report(rep))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
