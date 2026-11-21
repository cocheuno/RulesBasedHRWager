"""A wrong day's charts are refused: each chart's own date and horse names must be the card's (Belmont 11/20 was
processed with Belmont 11/19's charts and every result was the previous day's)."""
from __future__ import annotations

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

from synthetic_card import build_card                 # noqa: E402
from brisnet_pp.chart import chart_date               # noqa: E402
from handicapper.results import check_identity        # noqa: E402


def result_for(card, race_no, names, date=None):
    r = {"race_no": race_no, "finish": ["1", "2", "3"], "runners": [{"pgm": str(i + 1), "name": n} for i, n in enumerate(names)]}
    if date:
        r["date"] = date
    return {"track": card["track"], "date": card["date"], "races": [r]}


class TestIdentity(unittest.TestCase):
    def setUp(self):
        self.card = build_card()
        self.r1 = [h["name"] for h in self.card["races"][0]["horses"]]

    def test_right_horses_pass(self):
        self.assertEqual(check_identity(self.card, result_for(self.card, 1, self.r1[:5])), "verified")
        self.assertEqual(check_identity(self.card, result_for(self.card, 1, [self.r1[0].upper(), self.r1[1] + " (IRE)", self.r1[2]])), "verified")

    def test_another_days_horses_are_refused(self):
        with self.assertRaises(ValueError) as cm:
            check_identity(self.card, result_for(self.card, 1, ["Beauty Truth Good", "Tia Melanie", "Girls Wear Pearls", "Other One"]))
        self.assertIn("are not this card's race 1 (0 of 4 names match)", str(cm.exception))

    def test_chart_date(self):
        self.assertEqual(chart_date("November 19, 2026"), "2026-11-19"); self.assertIsNone(chart_date("garbage")); self.assertIsNone(chart_date(None))
        with self.assertRaises(ValueError) as cm:
            check_identity(self.card, result_for(self.card, 1, self.r1[:4], date="2026-11-05"))
        self.assertIn("chart is dated 2026-11-05", str(cm.exception))

    def test_few_runners_are_not_judged(self):
        self.assertEqual(check_identity(self.card, result_for(self.card, 1, ["Someone", "Else"])), "verified")   # fewer than 3 names: no verdict


class TestUpload(unittest.TestCase):
    def test_chart_named_for_another_day_or_track_is_refused(self):
        from ui.server import Desk
        tmp = tempfile.mkdtemp()
        try:
            shutil.copy(os.path.join(ROOT, "rules_config.json"), os.path.join(tmp, "rules_config.json")); os.makedirs(os.path.join(tmp, "data", "out"))
            with open(os.path.join(tmp, "data", "out", "dmr1106y.card.json"), "w", encoding="utf-8") as fh:
                json.dump(build_card(), fh)
            d = Desk(tmp); d.run("dmr1106y")
            with self.assertRaises(ValueError) as cm:
                d.save_upload("dmr1106y", "chart", "20261105DMRUSA3.pdf", b"%PDF-1.4")
            self.assertIn("chart is dated 2026-11-05", str(cm.exception))
            with self.assertRaises(ValueError) as cm:
                d.save_upload("dmr1106y", "chart", "20261106BELUSA3.pdf", b"%PDF-1.4")
            self.assertIn("chart is for BEL", str(cm.exception))
            self.assertTrue(d.save_upload("dmr1106y", "chart", "20261106DMRUSA3.pdf", b"%PDF-1.4")["saved"].endswith("r3.pdf"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
