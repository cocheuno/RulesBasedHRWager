"""
Rule-level tests on the synthetic card (tests/synthetic_card.py).

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from synthetic_card import build_card                      # noqa: E402
from handicapper.engine import load_config, score_card, score_race, rules_doc   # noqa: E402
from handicapper import rules as R                         # noqa: E402
from handicapper import multirace as MR                    # noqa: E402


def hits(sheet, rule_id):
    return [h for h in sheet["hits"] if h["rule"] == rule_id]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.card = build_card()
        cls.cfg = load_config(os.path.join(os.path.dirname(HERE), "rules_config.json"))
        cls.result = score_card(cls.card, cls.cfg)
        cls.by_race = {r["race_no"]: r for r in cls.result["races"]}

    def sheet(self, race_no, name):
        return next(s for s in self.by_race[race_no]["sheets"] if s["name"] == name)


class TestInvariants(Base):
    def test_no_rule_errors(self):
        for r in self.result["races"]:
            for s in r["sheets"]:
                for h in s["hits"]:
                    self.assertNotIn("RULE ERROR", h["note"], f"R{r['race_no']} {s['name']}: {h}")

    def test_every_point_traces_to_a_rule(self):
        ids = {rl.id for rl in R.RULES}
        for r in self.result["races"]:
            for s in r["sheets"]:
                self.assertAlmostEqual(s["score"], round(sum(h["points"] for h in s["hits"]), 2), places=1)
                for h in s["hits"]:
                    self.assertIn(h["rule"], ids)
                    self.assertTrue(h["note"])

    def test_deterministic(self):
        again = score_card(build_card(), self.cfg)
        self.assertEqual([r["picks"] for r in again["races"]], [r["picks"] for r in self.result["races"]])
        self.assertEqual(again["multirace"], self.result["multirace"])

    def test_rule_ids_unique_and_documented(self):
        ids = [rl.id for rl in R.RULES] + [rl.id for rl in MR.HRULES]
        self.assertEqual(len(ids), len(set(ids)))
        for rl in R.RULES + MR.HRULES:
            self.assertIn("Basis:", rl.doc, f"{rl.id} has no expert basis in its docstring")
        doc = rules_doc()
        for rl in R.RULES + MR.HRULES:
            self.assertIn(f"| {rl.id} |", doc)


class TestSpeedRules(Base):
    def test_s6_bounce_outweighs_m4_on_career_top(self):
        s = self.sheet(4, "Big Figure Bounce")
        self.assertTrue(hits(s, "S6"))
        self.assertLess(hits(s, "S6")[0]["points"], -6)
        self.assertFalse(hits(s, "M4"), "M4 must not reward the same leap S6 penalises")

    def test_s9_figure_standout(self):
        s = self.sheet(5, "Standout")
        self.assertTrue(hits(s, "S9"))
        self.assertFalse(hits(self.sheet(4, "Big Figure Bounce"), "S9"), "career tops are excluded from S9")

    def test_s8_pairing(self):
        s = self.sheet(4, "Steady Eddie")   # 80, 80, 79 vs par 83
        self.assertTrue(hits(s, "S8"))


class TestClassRules(Base):
    def test_c6_claimed_and_dropped(self):
        s = self.sheet(2, "Claimed Then Dropped")
        h = hits(s, "C6")
        self.assertTrue(h)
        self.assertLess(h[0]["points"], 0)

    def test_c7_first_time_for_tag(self):
        s = self.sheet(2, "Tag Virgin")
        self.assertTrue(hits(s, "C7"))
        self.assertFalse(hits(self.sheet(2, "Lone Rocket"), "C7"))

    def test_c8_back_class(self):
        self.assertTrue(hits(self.sheet(4, "Back Classer"), "C8"))

    def test_c9_maiden_graduates(self):
        mcl = hits(self.sheet(3, "Fresh Grad"), "C9")
        self.assertTrue(mcl)
        self.assertLess(mcl[0]["points"], 0)
        # MSW graduate whose winning figure (87) beats par (84) is waived (0 points -> not recorded)
        self.assertFalse(hits(self.sheet(3, "Msw Grad"), "C9"))

    def test_c10_drop_after_win(self):
        h = hits(self.sheet(2, "Drop Off Win"), "C10")
        self.assertTrue(h)
        self.assertLess(h[0]["points"], 0)

    def test_c1_discounts_declining_dropper(self):
        h = hits(self.sheet(2, "Tailing Off"), "C1")
        self.assertFalse(h, "Tailing Off is at the same level; no drop")


class TestPaceFormRules(Base):
    def test_p1_lone_speed(self):
        self.assertTrue(hits(self.sheet(2, "Lone Rocket"), "P1"))
        self.assertEqual(self.by_race[2]["lone_speed"], "1")

    def test_p9_e1_leader_and_duel(self):
        self.assertTrue(hits(self.sheet(2, "Lone Rocket"), "P9"))
        # R6: three E types average E1 97 / 96 / 96 -> all three are in the projected duel
        duel = [hits(self.sheet(6, n), "P9") for n in ("Chalk Speed", "Rival Speed", "Third Speed")]
        self.assertTrue(all(duel))
        self.assertTrue(all(d[0]["points"] < 0 for d in duel))
        self.assertFalse(hits(self.sheet(6, "Ship In"), "P9"))   # E/P a point back is not an E dueller

    def test_p2_hot_pace(self):
        self.assertEqual(self.by_race[3]["pace_shape"], "hot")
        self.assertGreater(hits(self.sheet(3, "Late Thunder"), "P2")[0]["points"], 0)
        self.assertLess(hits(self.sheet(3, "Speedy One"), "P2")[0]["points"], 0)

    def test_f11_trouble_pattern(self):
        self.assertTrue(hits(self.sheet(4, "Trouble Magnet"), "F11"))

    def test_f12_pressured_effort(self):
        self.assertTrue(hits(self.sheet(2, "Lone Rocket"), "F12"))

    def test_f13_beaten_favourite(self):
        h = hits(self.sheet(2, "Beaten Chalk"), "F13")
        self.assertTrue(h)
        self.assertGreater(h[0]["points"], 0)

    def test_f14_freshened(self):
        self.assertTrue(hits(self.sheet(4, "Fresh Legs"), "F14"))

    def test_f15_fast_loser(self):
        self.assertTrue(hits(self.sheet(3, "Fast Loser"), "F15"))


class TestMaidensAndEliminations(Base):
    def test_m2_msw_dropper_wins_r1(self):
        self.assertTrue(hits(self.sheet(1, "Dropping Dream"), "M2"))
        self.assertIn("1", self.by_race[1]["picks"])

    def test_m1_debut_m3_chronic(self):
        self.assertTrue(hits(self.sheet(1, "Fresh Face"), "M1"))
        self.assertTrue(hits(self.sheet(1, "Sucker Punch"), "M3"))

    def test_m4_second_time_starter(self):
        self.assertTrue(hits(self.sheet(1, "Second Timer"), "M4"))

    def test_x_rules(self):
        self.assertTrue(self.sheet(1, "Rusty Gate")["eliminated"])          # X2 long layoff
        self.assertTrue(self.sheet(2, "Out Of Sorts")["eliminated"])        # X1 / X4
        self.assertEqual(self.sheet(1, "Also Ran")["flags"], ["AE - needs a scratch to run"])
        self.assertNotIn("7", self.by_race[1]["picks"])


class TestWeights(Base):
    def test_prime_power_and_comment_weights_are_moderate(self):
        w = {rl.id: rl.weight for rl in R.RULES}
        self.assertLessEqual(w["S7"], w["S1"])
        self.assertLess(w["Q1"], 1.0)
        self.assertLess(w["Q2"], 1.0)

    def test_config_override_changes_score(self):
        cfg = load_config(None)
        cfg["weights"]["S1"] = 0
        cfg["disabled"] = ["S7"]
        r = score_race(self.card["races"][5], cfg)
        for s in r["sheets"]:
            self.assertFalse(hits(s, "S1"))
            self.assertFalse(hits(s, "S7"))


if __name__ == "__main__":
    unittest.main()
