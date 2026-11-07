"""Wagering analysis: structured wagers, combo counting, evaluation against results, roll-up."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from synthetic_card import build_card                          # noqa: E402
from handicapper.engine import load_config, score_card        # noqa: E402
from handicapper.wagering import combos, evaluate_card, evaluate_wager, make_wager, rollup, format_evaluation, format_rollup  # noqa: E402

CFG = load_config(os.path.join(os.path.dirname(HERE), "rules_config.json"))


class TestCombos(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(len(combos([["1"], ["2", "3", "4"]])), 3)                       # exacta key
        self.assertEqual(len(combos([["1"], ["2", "3", "4"], ["2", "3", "4", "5"]])), 9)  # trifecta key
        self.assertEqual(len(combos([["1", "2"], ["1", "2"]], box=True)), 2)              # exacta box
        self.assertEqual(len(combos([["1", "2", "3"]] * 3, box=True)), 6)                 # trifecta box
        self.assertEqual(len(combos([["1", "2"], ["1", "2", "3"]])), 4)                   # part-wheel
        self.assertEqual(len(combos([["4", "1"], ["6"], ["1", "6"]], multi=True)), 4)     # pick 3 ticket: #1 in two races is fine
        self.assertEqual(len(combos([["7", "1"], ["7", "8", "4"]], multi=True)), 6)         # daily double likewise

    def test_evaluate(self):
        by = {4: {"race_no": 4, "finish": ["7", "4", "8", "6"], "win": 8.0,
                  "exotics": [{"type": "EXACTA", "base": 1.0, "combo": "7/4", "payout": 30.10},
                              {"type": "TRIFECTA", "base": 0.5, "combo": "7/4/8", "payout": 66.05}]},
              5: {"race_no": 5, "finish": ["2", "7"], "win": 7.6, "exotics": [{"type": "DOUBLE", "base": 2.0, "combo": "7/2", "payout": 27.80}]}}
        w = evaluate_wager(make_wager("WIN", [["7"]], race_no=4), by, 1.0)
        self.assertEqual((w["hit"], w["ret"], w["cost"]), (True, 4.0, 1.0))
        k = evaluate_wager(make_wager("EXACTA", [["7"], ["1", "6", "10"]], race_no=4), by, 1.0)
        self.assertEqual((k["hit"], k["cost"]), (False, 3.0))
        k2 = evaluate_wager(make_wager("EXACTA", [["7"], ["4", "6"]], race_no=4), by, 1.0)
        self.assertEqual((k2["hit"], k2["ret"]), (True, 30.10))
        t = evaluate_wager(make_wager("TRIFECTA", [["7"], ["4", "8"], ["4", "8", "6"]], race_no=4), by, 1.0)
        self.assertEqual((t["hit"], t["ret"]), (True, 132.10))
        dd = evaluate_wager(make_wager("DOUBLE", [["7", "1"], ["6", "2"]], races=[4, 5]), by, 1.0)
        self.assertEqual((dd["hit"], dd["ret"], dd["cost"]), (True, 13.9, 4.0))
        unk = evaluate_wager(make_wager("SUPERFECTA", [["7"], ["4"], ["8"], ["6"]], race_no=4), by, 1.0)
        self.assertTrue(unk["hit"] and unk["ret"] is None and not unk["known"], "no superfecta payout on file")


class TestCard(unittest.TestCase):
    def test_structured_wagers_match_text(self):
        res = score_card(build_card(), CFG)
        for r in res["races"]:
            self.assertTrue(r["wagers"], f"R{r['race_no']} has no structured wagers")
            others = [w for w in r["wagers"] if w["source"] == "other"]
            self.assertEqual(len(others), sum(1 for t in r["other_wagers"] if not t.startswith("no WIN") and not t.startswith("PASS")))
            for w in r["wagers"]:
                self.assertGreater(w["combos"], 0)
        r5 = next(r for r in res["races"] if r["race_no"] == 5)       # 4/5 standout: no WIN bet, keys only
        self.assertFalse([w for w in r5["wagers"] if w["type"] == "WIN"])

    def test_dedupe_counts_each_combination_once(self):
        from handicapper.wagering import card_wagers
        res = score_card(build_card(), CFG)
        ws = card_wagers(res, CFG["wagering"])
        r2 = [w for w in ws if w["race_no"] == 2 and len(w["races"]) == 1]
        wins = [w for w in r2 if w["type"] == "WIN"]
        self.assertEqual(len(wins), 1, "primary WIN and 'other' WIN on the same horse are one bet")
        self.assertEqual(wins[0]["source"], "primary")
        for a in r2:
            for b in r2:
                if a is not b and a["type"] == b["type"]:
                    ca, cb = set(combos(a["legs"], a["box"])), set(combos(b["legs"], b["box"]))
                    self.assertFalse(ca < cb, f"{a['label']} is covered by {b['label']}")

    def test_evaluate_card_and_rollup(self):
        res = score_card(build_card(), CFG)
        results = {"races": [{"race_no": 2, "finish": ["1", "3", "5", "4"], "win": 8.0,
                               "exotics": [{"type": "EXACTA", "base": 1.0, "combo": "1/3", "payout": 20.0}]},
                              {"race_no": 5, "finish": ["1", "2", "3"], "win": 3.6}]}
        ev = evaluate_card(res, results, CFG["wagering"])
        self.assertEqual(ev["unit"], 1.0)
        r2 = [x for x in ev["rows"] if x["race_no"] == 2 and len(x["races"]) == 1]
        self.assertTrue(any(x["type"] == "WIN" and x["hit"] and x["ret"] == 4.0 for x in r2))
        self.assertTrue(any(x["type"] == "EXACTA" and x["hit"] and x["ret"] == 20.0 for x in r2))
        self.assertTrue(any(not x["known"] for x in ev["rows"]), "races without results are unknown, not misses")
        ru = rollup([ev, ev])
        self.assertEqual(ru["all"]["bets"], 2 * ev["totals"]["bets"])
        self.assertEqual([c["track"] for c in ru["chart"]], ["DMR", "ALL"])
        self.assertEqual(ru["chart"][-1]["hits"], ru["all"]["hits"])
        self.assertIn("WIN", ru["by_type"])
        format_evaluation(ev); format_rollup(ru)


if __name__ == "__main__":
    unittest.main()
