"""Scratches, same-day bias (P10) and the back-test join."""
from __future__ import annotations

import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from synthetic_card import build_card                                          # noqa: E402
from handicapper.engine import load_config, score_card                         # noqa: E402
from handicapper.results import (apply_scratches, attach_day_bias, backtest,   # noqa: E402
                                 format_backtest, parse_scratch_spec)

CFG = load_config(os.path.join(os.path.dirname(HERE), "rules_config.json"))

# invented results for the synthetic card: early types win R1, R2, R4, R5 on dirt
RESULTS = {"track": "Del Mar", "date": "2026-11-06", "races": [
    {"race_no": 1, "finish": ["1", "6", "2", "5"], "win": 5.20},
    {"race_no": 2, "finish": ["1", "2", "3"], "win": 8.00},
    {"race_no": 3, "finish": ["4", "5", "7"], "win": 7.00},
    {"race_no": 4, "finish": ["2", "6", "4"], "win": 10.00},
    {"race_no": 5, "finish": ["1", "2", "3"], "win": 3.60},
]}


class TestScratches(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_scratch_spec("3:3, 4:6 8:4,8:9"), {3: ["3"], 4: ["6"], 8: ["4", "9"]})
        self.assertEqual(parse_scratch_spec("1:2, 1:+7, 1:-7a"), {1: ["2", "+7", "-7A"]})
        with self.assertRaises(ValueError):
            parse_scratch_spec("8-4")

    def test_apply_and_draw_in(self):
        card = build_card()
        notes = apply_scratches(card, {1: ["2"], 2: ["1"], 9: ["1"]})
        r1 = card["races"][0]
        self.assertNotIn("2", [h["pgm"] for h in r1["horses"]])
        ae = next(h for h in r1["horses"] if h["name"] == "Also Ran")
        self.assertIsNone(ae["entry_status"], "one AE draws in per scratch")
        self.assertEqual(r1["field_size"], 6)
        self.assertTrue(any("draws in" in n for n in notes))
        card2 = build_card()
        apply_scratches(card2, {1: ["7"]})          # scratching the AE itself draws nobody in
        self.assertFalse(any(h.get("entry_status") is None and h["name"] == "Also Ran" for h in card2["races"][0]["horses"]))
        self.assertEqual(len(card2["races"][0]["horses"]), 6)
        # official status beats the automatic rule: '-7' holds the AE out despite a scratch; '+7' puts it in without one
        card3 = build_card()
        notes3 = apply_scratches(card3, {1: ["2", "-7"]})
        self.assertEqual(next(h for h in card3["races"][0]["horses"] if h["name"] == "Also Ran")["entry_status"], "AE")
        self.assertTrue(any("held out" in n for n in notes3))
        card4 = build_card()
        notes4 = apply_scratches(card4, {1: ["+7"]})
        self.assertIsNone(next(h for h in card4["races"][0]["horses"] if h["name"] == "Also Ran")["entry_status"])
        self.assertTrue(any("officially in" in n for n in notes4))
        # scratching the lone speed in R2 changes the pace shape and the pick
        res = score_card(card, CFG)
        self.assertNotEqual(res["races"][1]["lone_speed"], "1")
        self.assertNotIn("1", res["races"][1]["picks"])


class TestDayBias(unittest.TestCase):
    def test_p10_fires_after_three_dirt_results(self):
        card = build_card()
        attach_day_bias(card, copy.deepcopy(RESULTS))
        self.assertEqual(card["races"][0]["day_bias"]["n"], 0)
        self.assertEqual(card["races"][4]["day_bias"]["n"], 3, "R5 (dirt) sees the R1, R2, R4 dirt winners")
        self.assertEqual(card["races"][5]["day_bias"]["n"], 1, "R6 (turf) sees only the R3 turf winner")
        res = score_card(card, CFG)
        r5 = res["races"][4]
        hits = [h for s in r5["sheets"] for h in s["hits"] if h["rule"] == "P10"]
        self.assertTrue(hits, "P10 should fire in R5 with 3 earlier dirt winners")
        early = next(s for s in r5["sheets"] if s["name"] == "Standout")
        self.assertGreater(next(h["points"] for h in early["hits"] if h["rule"] == "P10"), 0)
        res_plain = score_card(build_card(), CFG)
        self.assertFalse([h for s in res_plain["races"][4]["sheets"] for h in s["hits"] if h["rule"] == "P10"])


class TestIdentity(unittest.TestCase):
    def test_results_must_belong_to_the_card(self):
        from handicapper.results import check_identity
        from handicapper.wagering import evaluate_card
        card = build_card(); picks = score_card(card, CFG)
        good = {"track": card["track"], "date": card["date"], "races": [{"race_no": 2, "finish": ["1", "3", "5"], "win": 8.0}]}
        self.assertEqual(check_identity(picks, good), "verified")
        self.assertEqual(backtest(picks, good)["identity"], "verified")
        self.assertEqual(check_identity(picks, {"races": good["races"]}), "unverified", "no track/date: cannot be checked")
        self.assertEqual(check_identity(picks, {"track": "DMR", "date": card["date"], "races": []}), "verified", "track code matches the name")
        wrong_day = dict(good, date="2001-01-01")
        with self.assertRaises(ValueError): backtest(picks, wrong_day)
        with self.assertRaises(ValueError): evaluate_card(picks, wrong_day, CFG["wagering"])
        with self.assertRaises(ValueError): attach_day_bias(copy.deepcopy(card), dict(good, track="Wrong Track"))
        chart_from_elsewhere = dict(good, races=[dict(good["races"][0], track="Belmont Park")])
        with self.assertRaises(ValueError): backtest(picks, chart_from_elsewhere)


class TestBacktest(unittest.TestCase):
    def test_join(self):
        picks = score_card(build_card(), CFG)
        bt = backtest(picks, copy.deepcopy(RESULTS))
        self.assertEqual(bt["summary"]["races"], 5)
        rows = {r["race_no"]: r for r in bt["races"]}
        self.assertTrue(rows[1]["top_pick_won"])
        self.assertFalse(rows[4]["top_pick_won"])
        self.assertEqual(rows[4]["winner"], "2")
        self.assertIn("multirace", bt)
        txt = format_backtest(bt)
        self.assertIn("| S1 | pos |", txt)
        json.dumps(bt)   # serialisable


if __name__ == "__main__":
    unittest.main()
