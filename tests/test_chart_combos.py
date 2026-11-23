"""Winning combinations with several horses in one leg (Gulfstream 11/22 race 7: the Pick 4 printed as
6-7-6-1/3/4/5/8 - a dead heat for the win between #3 and #5, plus tickets on scratched #1, #4 and #8 moved to the
favourite #3).  The chart separates legs with '-' and horses in a leg with '/'; the results file keeps legs apart."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from brisnet_pp.chart import EXOTIC_RE, chart_combo                          # noqa: E402
from handicapper.wagering import _combo_list, _combo_set, evaluate_wager, make_wager   # noqa: E402


def leg(no, finish, **kw):
    return dict({"race_no": no, "finish": finish, "win": 4.0, "source": "chart", "exotics": []}, **kw)


R7 = leg(7, ["3", "5", "6", "7", "2"], winners=["3", "5"], dead_heats={"1": ["3", "5"]}, win_by={"3": 3.2, "5": 13.2},
         exotics=[{"type": "PICK4", "base": 0.5, "combo": chart_combo("6-7-6-1/3/4/5/8"), "payout": 331.4},
                  {"type": "EXACTA", "base": 1.0, "combo": chart_combo("3-5"), "payout": 7.0}])
BY = {4: leg(4, ["6", "1"]), 5: leg(5, ["7", "2"]), 6: leg(6, ["6", "4"]), 7: R7}


class TestChartCombo(unittest.TestCase):
    def test_legs_and_alternates(self):
        self.assertEqual(chart_combo("6-7-6-1/3/4/5/8"), "6/7/6/1,3,4,5,8")
        self.assertEqual(chart_combo("5/6-8-6-3"), "5,6/8/6/3")
        self.assertEqual(chart_combo("3-5"), "3/5")
        self.assertEqual(chart_combo("6/8"), "6/8", "a combination written with '/' only is already legs")
        self.assertEqual(_combo_list("6/7/6/1,3,4,5,8"), [["6"], ["7"], ["6"], ["1", "3", "4", "5", "8"]])
        self.assertEqual(_combo_set("3/5,6"), {("3", "5"), ("3", "6")})

    def test_read_from_chart_text(self):
        line = "50 CENT PICK 4 (6-7-6-1/3/4/5/8) PAID $331.40"
        m = next(EXOTIC_RE.finditer(line))
        self.assertEqual(chart_combo(m.group("combo")), "6/7/6/1,3,4,5,8")


class TestSettlement(unittest.TestCase):
    def test_pick4_through_a_leg_with_several_horses(self):
        for last in (["3"], ["5"], ["3", "9"]):
            r = evaluate_wager(make_wager("PICK4", [["6"], ["7"], ["6", "2"], last], races=[4, 5, 6, 7], race_no=7), BY, 0.5)
            self.assertTrue(r["hit"] and r["known"], last)
            self.assertEqual(r["ret"], 331.4, last)
        r = evaluate_wager(make_wager("PICK4", [["6"], ["7"], ["6"], ["6"]], races=[4, 5, 6, 7], race_no=7), BY, 0.5)
        self.assertFalse(r["hit"])

    def test_single_race_combo_with_alternates(self):
        by = {1: leg(1, ["3", "5", "6"], exotics=[{"type": "EXACTA", "base": 2.0, "combo": "3/5,6", "payout": 20.0}])}
        r = evaluate_wager(make_wager("EXACTA", [["3"], ["6"]], race_no=1), by, 2.0)
        self.assertTrue(r["hit"]); self.assertEqual(r["ret"], 20.0)
        r = evaluate_wager(make_wager("EXACTA", [["3"], ["5", "6"]], race_no=1), by, 2.0)
        self.assertEqual(r["ret"], 20.0, "one printed payoff pays once")


if __name__ == "__main__":
    unittest.main()
