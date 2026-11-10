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
            self.assertEqual(r["wager_status"], "BET" if r["wagers"] else "PASS")
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
        self.assertEqual(ev["units"]["WIN"], 2.0)
        self.assertEqual(ev["units"]["SUPERFECTA"], 0.10)
        r2 = [x for x in ev["rows"] if x["race_no"] == 2 and len(x["races"]) == 1]
        # $2 win stake returns the $2 payout; $1 exacta returns the per-dollar payout
        self.assertTrue(any(x["type"] == "WIN" and x["hit"] and x["unit"] == 2.0 and x["cost"] == 2.0 and x["ret"] == 8.0 for x in r2))
        self.assertFalse([x for x in r2 if x["type"] == "EXACTA"], "optional exotics are not recommended bets")
        for x in ev["rows"]:
            if x["type"] == "TRIFECTA":
                self.assertEqual(x["unit"], 0.5)
            if x["type"] == "SUPERFECTA":
                self.assertEqual(x["unit"], 0.1)
            if x["type"] in ("PICK3", "PICK4"):
                self.assertEqual(x["unit"], {"PICK3": 1.0, "PICK4": 0.5}[x["type"]], "Pick 3/4 priced at the ticket base")
        self.assertTrue(any(not x["known"] for x in ev["rows"]), "races without results are unknown, not misses")
        ru = rollup([ev, ev])
        self.assertEqual(ru["all"]["bets"], 2 * ev["totals"]["bets"])
        self.assertEqual([c["track"] for c in ru["chart"]], ["DMR", "ALL"])
        self.assertEqual(ru["chart"][-1]["hits"], ru["all"]["hits"])
        self.assertIn("WIN", ru["by_type"])
        txt = format_evaluation(ev); format_rollup(ru)
        self.assertIn("Unit stakes: $2 win, $1 exacta, $0.50 trifecta, $0.10 superfecta, $1 double, $1 Pick 3, $0.50 Pick 4.", txt)

    def test_win_bet_is_passed_when_final_odds_are_under_the_minimum(self):
        by = {4: {"race_no": 4, "finish": ["7", "2", "3"], "win": 3.6, "final_odds": {"7": 0.8, "2": 5.0}}}
        w = make_wager("WIN", [["7"]], race_no=4) | {"min_odds": 1.5, "min_odds_by": {"7": 1.5}}
        r = evaluate_wager(w, by, 2.0)
        self.assertFalse(r["placed"]); self.assertEqual(r["cost"], 0.0); self.assertFalse(r["hit"]); self.assertIn("passed at the window", r["note"])
        w2 = make_wager("WIN", [["7"]], race_no=4) | {"min_odds": 0.5, "min_odds_by": {"7": 0.5}}
        r2 = evaluate_wager(w2, by, 2.0)
        self.assertTrue(r2["placed"] and r2["hit"]); self.assertEqual((r2["cost"], r2["ret"]), (2.0, 3.6))
        # no final odds on file: the morning line decided, the bet stands
        by_no_fo = {4: {"race_no": 4, "finish": ["7"], "win": 3.6}}
        self.assertTrue(evaluate_wager(w, by_no_fo, 2.0)["placed"])
        # two overlays in one WIN line: only the one under its minimum is passed
        w3 = make_wager("WIN", [["7", "2"]], race_no=4) | {"min_odds_by": {"7": 1.5, "2": 3.0}}
        r3 = evaluate_wager(w3, by, 2.0)
        self.assertTrue(r3["placed"]); self.assertEqual(r3["cost"], 2.0); self.assertFalse(r3["hit"], "the winner was the horse that was passed")
        # totals and roll-up leave passed bets out
        w5 = make_wager("WIN", [["1"]], race_no=5) | {"min_odds_by": {"1": 1.5}}        # placed and hit in another race
        picks = {"source": "x", "track_code": "T", "races": [{"race_no": 4, "confidence": "high", "wagers": [w]},
                                                              {"race_no": 5, "confidence": "high", "wagers": [w5]}], "multirace": None}
        results = {"races": [by[4], {"race_no": 5, "finish": ["1", "2"], "win": 6.0, "final_odds": {"1": 2.0}}]}
        ev = evaluate_card(picks, results, {})
        self.assertEqual((ev["totals"]["bets"], ev["totals"]["passed"], ev["totals"]["hits"]), (1, 1, 1))
        ru = rollup([ev]); self.assertEqual((ru["all"]["bets"], ru["all"]["passed"]), (1, 1))
        self.assertIn("passed", format_evaluation(ev))

    def test_engine_win_wagers_carry_minimum_prices(self):
        res = score_card(build_card(), CFG)
        wins = [w for r in res["races"] for w in r["wagers"] if w["type"] == "WIN"]
        self.assertTrue(wins)
        for w in wins:
            self.assertEqual(set(w["min_odds_by"]), set(w["legs"][0]))
            self.assertTrue(all(v is not None and v >= 1.5 for v in w["min_odds_by"].values()))

    def test_trifecta_structure_by_confidence(self):
        res = score_card(build_card(), CFG)
        seen = set()
        for r in res["races"]:
            live = [s for s in r["sheets"] if not s["eliminated"] and not s["flags"]]
            tris = [w for w in r["wager_options"] if w["type"] == "TRIFECTA" and w["source"] == "other"]
            if r["confidence"] == "high" and len(live) >= 3:
                seen.add("high")
                a = live[0]["pgm"]
                self.assertTrue(any(w["legs"][0] == [a] for w in tris), "key first")
                self.assertTrue(any(w["legs"][1] == [a] and a not in w["legs"][0] for w in tris), "key second")
            elif r["confidence"] in ("medium", "low") and len(live) >= 4:
                seen.add(r["confidence"])
                box = [w for w in tris if w["box"]]
                self.assertTrue(box and len(box[0]["legs"][0]) == 4 and box[0]["combos"] == 24, "four-horse box")
        self.assertIn("high", seen); self.assertTrue(seen & {"medium", "low"})

    def test_multirace_tickets_tracked_not_counted(self):
        res = score_card(build_card(), CFG)
        results = {"races": [{"race_no": n, "finish": ["1", "2", "3"], "win": 4.0} for n in range(1, 7)]}
        ev = evaluate_card(res, results, CFG["wagering"])
        tracked = [x for x in ev["rows"] if x["tracked_only"]]
        self.assertTrue(tracked, "Pick 3/4 tickets are still evaluated")
        self.assertTrue(all(x["type"] in ("PICK3", "PICK4") for x in tracked))
        self.assertEqual(ev["totals"]["bets"], sum(1 for x in ev["rows"] if not x["tracked_only"] and x.get("placed", True)))
        self.assertEqual(ev["totals"]["tracked"]["tickets"], len(tracked))
        ru = rollup([ev])
        self.assertNotIn("PICK3", ru["by_type"]); self.assertNotIn("PICK4", ru["by_type"])
        self.assertEqual(ru["tracked_multirace"]["tickets"], len(tracked))
        self.assertIn("tracked, not counted as bets", format_evaluation(ev))
        ev2 = evaluate_card(res, results, dict(CFG["wagering"], count_multirace=True))
        self.assertEqual(ev2, ev, "saved policy and optional scenarios are unaffected by later switches")

    def test_pool_absent_from_chart_is_not_offered(self):
        chart = {"race_no": 3, "finish": ["2", "4", "6", "7"], "win": 3.6, "source": "chart",
                 "exotics": [{"type": "EXACTA", "base": 1.0, "combo": "2/4", "payout": 5.5}]}
        typed = dict(chart, source="manual")
        tri = make_wager("TRIFECTA", [["2"], ["4", "6"], ["4", "6", "7"]], race_no=3)
        r = evaluate_wager(tri, {3: chart}, 0.5)
        self.assertEqual((r["placed"], r["status"], r["cost"], r["hit"]), (False, "not offered", 0.0, False))
        self.assertIn("no trifecta pool", r["note"])
        r2 = evaluate_wager(tri, {3: typed}, 0.5)
        self.assertTrue(r2["placed"] and r2["hit"] and r2["ret"] is None and not r2["known"], "a typed result cannot say the pool was absent")
        ex = make_wager("EXACTA", [["2"], ["4"]], race_no=3)
        self.assertEqual(evaluate_wager(ex, {3: chart}, 1.0)["ret"], 5.5)
        # multi-race: the pool is on the last race's chart
        dbl = make_wager("DOUBLE", [["1"], ["2"]], race_no=2, races=[2, 3])
        by = {2: {"race_no": 2, "finish": ["1"], "source": "chart", "exotics": []}, 3: chart}
        self.assertEqual(evaluate_wager(dbl, by, 1.0)["status"], "not offered")
        picks = {"source": "x", "track_code": "T", "races": [{"race_no": 3, "confidence": "high", "wagers": [tri, ex]}], "multirace": None}
        ev = evaluate_card(picks, {"races": [chart]}, {})
        self.assertEqual((ev["totals"]["bets"], ev["totals"]["not_offered"], ev["totals"]["hits"]), (1, 1, 1))
        ru = rollup([ev]); self.assertEqual(ru["all"]["not_offered"], 1); self.assertNotIn("TRIFECTA", {k for k, d in ru["by_type"].items() if d["bets"]})
        self.assertIn("not offered", format_evaluation(ev))

    def test_no_trifecta_or_superfecta_below_pool_minimum(self):
        card = build_card()
        for race in card["races"]:
            race["horses"] = race["horses"][:4]          # four starters everywhere
        res = score_card(card, CFG)
        for r in res["races"]:
            self.assertFalse([w for w in r["wager_options"] if w["type"] in ("TRIFECTA", "SUPERFECTA")], f"R{r['race_no']} suggested an exotic the track would not offer")
            if len([s for s in r["sheets"] if not s["eliminated"] and not s["flags"]]) >= 3:
                self.assertTrue(any("no trifecta" in w for w in r["option_notes"]), f"R{r['race_no']} should say why")

    def test_unit_for_old_config(self):
        from handicapper.wagering import unit_for
        self.assertEqual(unit_for({"type": "WIN"}, {"unit": 1.0}), 1.0, "single-unit config still honoured")
        self.assertEqual(unit_for({"type": "WIN"}, {}), 2.0)
        self.assertEqual(unit_for({"type": "PICK3", "unit": 3.0}, {}), 3.0, "a ticket's own denomination wins")


if __name__ == "__main__":
    unittest.main()
