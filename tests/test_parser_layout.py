"""Parser layout fixes from Churchill 11/20: a race without pars starts its pages higher (the first horse of each
continuation page was cut off), and workouts on an all-weather track carry the all-weather marker after the track."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from brisnet_pp.parser import PARS_ROW_RE, WORK_RE, BrisnetPPParser as Parser   # noqa: E402


class FakeRow:
    def __init__(self, top, text):
        self.top, self._t = top, text

    def text(self, *a, **k):
        return self._t


class TestBodyTop(unittest.TestCase):
    def test_page_without_pars_line(self):
        rows = [FakeRow(16.5, "Churchill Downs Race 9"),
                FakeRow(18.4, "Ultimate PP's w/ QuickPlay Comments OC 100000n3x 1 Mile (T) 3&up Friday, November 20, 2026"),
                FakeRow(29.6, "3 Plensa (S 0) Dkbbr. g. 4 Prime Power: 153.4 (1st) Life: 12")]
        top = Parser._body_top(rows)
        self.assertLess(top, 29.6); self.assertGreater(top, 18.4)       # the horse row is in the body

    def test_page_with_pars_line_keeps_the_old_start(self):
        rows = [FakeRow(26.5, "Churchill Downs Race 8 E1 E2 / Late SPD"),
                FakeRow(28.4, "Ultimate PP's w/ QuickPlay Comments OC 80000n2x 6 Furlongs 3&up Friday, November 20, 2026"),
                FakeRow(33.1, "96 103 / 93 96"), FakeRow(43.5, "3 Master Controller (E/P 0) B. c. 4 Prime Power: 128.4")]
        self.assertEqual(Parser._body_top(rows), 31.4)
        self.assertTrue(PARS_ROW_RE.match("96 103 / 93 96"))           # the header's pars figures are dropped from the body
        self.assertFalse(PARS_ROW_RE.match("3 Master Controller (E/P 0)"))
        self.assertEqual(Parser._body_top([FakeRow(60, "anything")]), 40.0)   # no header line found: the old fixed start


class TestWorks(unittest.TestCase):
    def test_all_weather_marker(self):
        t = "×12Nov TP Ì 5f ft 1:01 B 1/13 ×04Nov TP Ì 5f ft 1:01 B 1/5 27Oct Kee 4f ft :48 B 3/9"
        got = [(m.group("date"), m.group("trk"), bool(m.group("aw")), m.group("dist")) for m in WORK_RE.finditer(t)]
        self.assertEqual(got, [("12Nov", "TP", True, "5f"), ("04Nov", "TP", True, "5f"), ("27Oct", "Kee", False, "4f")])


if __name__ == "__main__":
    unittest.main()
