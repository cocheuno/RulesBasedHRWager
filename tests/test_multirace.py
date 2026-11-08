"""Pick 3 / Pick 4 construction tests (handicapper/multirace.py)."""
from __future__ import annotations

import copy
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from synthetic_card import build_card                                   # noqa: E402
from handicapper.engine import load_config, score_card                  # noqa: E402
from handicapper import multirace as MR                                 # noqa: E402


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config(os.path.join(os.path.dirname(HERE), "rules_config.json"))
        cls.result = score_card(build_card(), cls.cfg)
        cls.mr = cls.result["multirace"]
        cls.by_race = {r["race_no"]: r for r in cls.result["races"]}


class TestLegs(Base):
    def leg(self, key, race_no):
        return next(l for w in self.mr[key]["windows"] for l in w["legs"] if l["race_no"] == race_no)

    def test_probabilities_sum_to_one_over_live_horses(self):
        for w in self.mr["pick4"]["windows"]:
            for l in w["legs"]:
                self.assertAlmostEqual(sum(l["probs"].values()), 1.0, places=2)

    def test_single_where_standout(self):
        l = self.leg("pick4", 5)
        self.assertEqual(l["kind"], "single")
        self.assertEqual(l["A"], ["1"])
        self.assertEqual(l["B"], [])
        self.assertTrue(any(a.startswith("H2") for a in l["audit"]))

    def test_bounce_candidate_is_never_a_single(self):
        l = self.leg("pick4", 4)
        self.assertNotEqual(l["kind"], "single")
        self.assertGreaterEqual(len(l["A"]) + len(l["B"]), 2)

    def test_vulnerable_favourite_demoted_to_b(self):
        l = self.leg("pick4", 6)      # 8/5 favourite is an E type into a hot pace with bounce risk
        self.assertTrue(l["price_leg"])
        self.assertEqual(l["favorite"], "1")
        self.assertNotIn("1", l["A"])
        self.assertIn("1", l["B"])
        self.assertTrue(any(a.startswith("H5 vulnerable favourite") for a in l["audit"]))

    def test_legitimate_favourite_stays_a(self):
        l = self.leg("pick4", 3)
        self.assertFalse(l["price_leg"])
        self.assertIn(l["favorite"], l["A"])

    def test_eliminated_and_ae_never_on_tickets(self):
        for key in ("pick3", "pick4"):
            for w in self.mr[key]["windows"]:
                for l in w["legs"]:
                    sheets = {s["pgm"]: s for s in self.by_race[l["race_no"]]["sheets"]}
                    for pgm in l["A"] + l["B"]:
                        self.assertFalse(sheets[pgm]["eliminated"])
                        self.assertFalse(sheets[pgm]["flags"])
        # the AE in race 1 is reported as an alternate (when it ranks top-3) rather than used
        l1 = next(l for w in self.mr["pick3"]["windows"] for l in w["legs"] if l["race_no"] == 1)
        ae = next(s for s in self.by_race[1]["sheets"] if s["pgm"] == "7")
        self.assertTrue(ae["flags"])
        self.assertEqual(any(a.startswith("H6 #7") for a in l1["audit"]), ae["rank"] <= 3)


class TestTickets(Base):
    def test_ticket_structure_and_cost(self):
        for key in ("pick3", "pick4"):
            for w in self.mr[key]["windows"]:
                main = w["tickets"][0]
                self.assertEqual(main["legs"], [l["A"] for l in w["legs"]])
                n_b = sum(1 for l in w["legs"] if l["B"])
                self.assertEqual(len(w["tickets"]), 1 + n_b)
                total = sum(math.prod(len(x) for x in t["legs"]) for t in w["tickets"]) * w["base"]
                self.assertAlmostEqual(total, w["cost"], places=2)
                self.assertLessEqual(w["cost"], w["budget"] + 1e-9)

    def test_hit_probability_formula(self):
        w = self.mr["pick4"]["recommended"]
        PA = [l["price_factor"] * sum(l["probs"][k] for k in l["A"]) for l in w["legs"]]
        PB = [l["price_factor"] * sum(l["probs"][k] for k in l["B"]) for l in w["legs"]]
        hit = math.prod(PA) + sum(PB[i] * math.prod(PA[j] for j in range(4) if j != i) for i in range(4))
        self.assertAlmostEqual(hit, w["hit_prob"], places=3)
        self.assertTrue(all(0.5 <= l["price_factor"] <= 1.0 for l in w["legs"]))
        self.assertTrue(any(l["price_factor"] < 1.0 for l in w["legs"]), "a leg with eliminated horses prices below 1")
        self.assertLess(w["all_favorites_prob"], w["hit_prob"])

    def test_budget_trim_respects_singles_and_records_notes(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["multirace"]["pick4"]["budget"] = 5.0
        res = score_card(build_card(), cfg)
        w = res["multirace"]["pick4"]["recommended"]
        self.assertLessEqual(w["cost"], 5.0)
        self.assertTrue(any(n.startswith("H8") for n in w["notes"]))
        single = next(l for l in w["legs"] if l["kind"] == "single")
        self.assertEqual(single["A"], ["1"])
        for l in w["legs"]:
            self.assertGreaterEqual(len(l["A"]), 1)

    def test_windows_ranked_by_score(self):
        for key in ("pick3", "pick4"):
            scores = [w["score"] for w in self.mr[key]["windows"]]
            self.assertEqual(scores, sorted(scores, reverse=True))
            self.assertEqual(self.mr[key]["recommended"]["name"], self.mr[key]["windows"][0]["name"])
            self.assertEqual(len(self.mr[key]["windows"]), 6 - (3 if key == "pick3" else 4) + 1)

    def test_h10_offered_windows(self):
        card = build_card()
        menus = {1: "$1 Exacta / 50c Rolling Pick 3 / 50c Early Pick 4", 2: "50c Rolling Pick 3", 3: "$3 Late Pick 3 / 50c Late Pick 4",
                 4: "$1 Exacta", 5: "$1 Exacta", 6: "$1 Exacta / $3 Turf Pick 3 (R2-4-6)"}
        for r in card["races"]:
            r["wagers"] = menus[r["race_no"]]
        res = score_card(card, self.cfg)
        p3, p4 = res["multirace"]["pick3"], res["multirace"]["pick4"]
        self.assertEqual(p3["offered"], {"1": 0.5, "2": 0.5, "3": 3.0})
        self.assertEqual(sorted(w["races"][0] for w in p3["windows"]), [1, 2, 3])
        self.assertEqual(next(w for w in p3["windows"] if w["races"][0] == 3)["base"], 3.0, "menu minimum above the configured base applies")
        self.assertEqual(next(w for w in p3["windows"] if w["races"][0] == 1)["base"], 1.0, "50c Pick 3 is bet at the configured $1")
        self.assertTrue(all(w["base"] == 0.5 for w in p4["windows"]))
        self.assertEqual(p4["offered"], {"1": 0.5, "3": 0.5})
        self.assertEqual(sorted(w["races"][0] for w in p4["windows"]), [1, 3])
        self.assertTrue(all(any(n.startswith("H10") for n in w["notes"]) for w in p3["windows"]))
        # no menu at all: every window, profile base
        res2 = score_card(build_card(), self.cfg)
        self.assertEqual(res2["multirace"]["pick3"]["offered"], {})
        self.assertEqual(len(res2["multirace"]["pick3"]["windows"]), 4)

    def test_no_multi_option(self):
        res = score_card(build_card(), self.cfg, multirace=False)
        self.assertIsNone(res["multirace"])

    def test_top3_and_other_wagers(self):
        from handicapper.engine import format_report
        txt = format_report(self.result, detail=0)
        for r in self.result["races"]:
            self.assertIn(f"### Race {r['race_no']}:", txt)
            self.assertTrue(r["other_wagers"], f"R{r['race_no']} has no wager suggestions")
            self.assertIn(r["leg"]["kind"], ("single", "standard", "chaos"))
        r5 = self.by_race[5]                      # 4/5 standout: key, no win bet, single in horizontals
        self.assertTrue(any(w.startswith("EXACTA key #1") for w in r5["other_wagers"]))
        self.assertTrue(any("no WIN bet" in w and "single" in w for w in r5["other_wagers"]))
        r6 = self.by_race[6]                      # beatable 8/5 favourite: chalk underneath only
        self.assertTrue(any("favourite #1 looks beatable" in w for w in r6["other_wagers"]))
        r4 = self.by_race[4]                      # daily double into R5's single
        self.assertTrue(any(w.startswith("DAILY DOUBLE") and "R5 #1" in w for w in r4["other_wagers"]))
        self.assertFalse(any(w.startswith("DAILY DOUBLE") for w in r6["other_wagers"]))   # last race: no next leg
        self.assertIn("| 1 | 1 | Standout |", txt)

    def test_report_section_present(self):
        from handicapper.engine import format_report
        txt = format_report(self.result, detail=2)
        self.assertLess(txt.index("## Wagering summary"), txt.index("## Race details"))
        self.assertLess(txt.index("## Race details"), txt.index("## Multi-race wagers"))
        self.assertIn("### Race 5: Alw 60000n2x", txt)
        terse = format_report(self.result, detail=0)
        self.assertIn("## Wagering summary", terse)
        self.assertNotIn("## Race details", terse)
        self.assertIn("## Multi-race wagers", txt)
        self.assertIn("Pick 4", txt)
        self.assertIn("H5 vulnerable favourite", txt)


if __name__ == "__main__":
    unittest.main()
