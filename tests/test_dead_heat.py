"""Dead heats and disqualifications (Churchill 11/20 race 9: #6 and #9 dead-heated for the win, #8 was placed
sixth): every winner counts, each pays its own price, and exotics pay every combination the chart paid."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from handicapper.results import win_price_of, winners_of          # noqa: E402
from handicapper.wagering import evaluate_wager, make_wager        # noqa: E402
from handicapper import evaluation as EV                            # noqa: E402

R9 = {"race_no": 9, "finish": ["6", "9", "3", "7", "2", "8", "5", "4"], "winners": ["6", "9"], "dead_heats": {"1": ["6", "9"]},
      "win": 6.72, "win_by": {"6": 6.72, "9": 7.96}, "place": {"6": 6.08, "9": 7.28}, "show": {"6": 3.84, "9": 4.72, "3": 3.08}, "source": "chart",
      "exotics": [{"type": "EXACTA", "base": 2.0, "combo": "6/9", "payout": 36.26}, {"type": "EXACTA", "base": 2.0, "combo": "9/6", "payout": 36.24},
                  {"type": "TRIFECTA", "base": 0.5, "combo": "6/9/3", "payout": 27.96}, {"type": "TRIFECTA", "base": 0.5, "combo": "9/6/3", "payout": 30.78},
                  {"type": "DOUBLE", "base": 1.0, "combo": "2/6", "payout": 19.28}, {"type": "DOUBLE", "base": 1.0, "combo": "2/9", "payout": 14.2}]}
R8 = {"race_no": 8, "finish": ["2", "5", "1"], "win": 5.5, "source": "chart", "exotics": []}
BY = {8: R8, 9: R9}


class TestHelpers(unittest.TestCase):
    def test_winners_and_prices(self):
        self.assertEqual(winners_of(R9), ["6", "9"]); self.assertEqual(winners_of(R8), ["2"]); self.assertEqual(winners_of(None), [])
        self.assertEqual((win_price_of(R9, "6"), win_price_of(R9, "9"), win_price_of(R9, "3")), (6.72, 7.96, None))
        self.assertEqual(win_price_of(R8, "2"), 5.5)


class TestSettlement(unittest.TestCase):
    def ev(self, w, unit):
        return evaluate_wager(w, BY, unit)

    def test_win_place_show(self):
        r = self.ev(make_wager("WIN", [["9"]], race_no=9), 2.0)
        self.assertTrue(r["hit"]); self.assertEqual(r["ret"], 7.96)                       # the second dead-heater wins too
        r = self.ev(make_wager("WIN", [["6", "9"]], race_no=9), 2.0)
        self.assertEqual((r["cost"], r["ret"]), (4.0, 14.68))                             # both: each pays its own price
        self.assertFalse(self.ev(make_wager("WIN", [["3"]], race_no=9), 2.0)["hit"])
        self.assertEqual(self.ev(make_wager("PLACE", [["9"]], race_no=9), 2.0)["ret"], 7.28)
        self.assertEqual(self.ev(make_wager("SHOW", [["3"]], race_no=9), 2.0)["ret"], 3.08)

    def test_exotics_pay_every_combination_covered(self):
        r = self.ev(make_wager("EXACTA", [["9"], ["6"]], race_no=9), 1.0)
        self.assertTrue(r["hit"]); self.assertEqual(r["ret"], 18.12)                      # 9-6 paid $36.24 for $2
        r = self.ev(make_wager("EXACTA", [["6", "9"], ["6", "9"]], True, race_no=9), 1.0)
        self.assertEqual((r["cost"], r["ret"]), (2.0, 36.25))                            # the box collects both
        r = self.ev(make_wager("TRIFECTA", [["9"], ["6", "3"], ["6", "3"]], race_no=9), 0.5)
        self.assertEqual(r["ret"], 30.78)
        self.assertFalse(self.ev(make_wager("EXACTA", [["6"], ["3"]], race_no=9), 1.0)["hit"])

    def test_double_through_a_dead_heat(self):
        r = self.ev(make_wager("DOUBLE", [["2"], ["9"]], race_no=9, races=[8, 9]), 1.0)
        self.assertTrue(r["hit"]); self.assertEqual(r["ret"], 14.2)
        r = self.ev(make_wager("DOUBLE", [["2"], ["6", "9"]], race_no=9, races=[8, 9]), 1.0)
        self.assertEqual(r["ret"], 33.48)
        self.assertFalse(self.ev(make_wager("DOUBLE", [["5"], ["6"]], race_no=9, races=[8, 9]), 1.0)["hit"])


class TestEvaluation(unittest.TestCase):
    def test_combined_probability(self):
        v = {"6": 0.3, "9": 0.2, "3": 0.5}
        self.assertAlmostEqual(EV.log_loss(v, ["6", "9"], 0.001), EV.log_loss({"x": 0.5, "3": 0.5}, "x", 0.001), places=6)
        self.assertAlmostEqual(EV.brier(v, ["6", "9"]), (0.3 - 0.5) ** 2 + (0.2 - 0.5) ** 2 + 0.5 ** 2, places=6)


if __name__ == "__main__":
    unittest.main()
