"""Racing Dudes' tickets and Timeform's Power Picks settled bet type by bet type beside the engine on the same races."""
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

from synthetic_card import build_card                     # noqa: E402
from handicapper import sources as SRC                    # noqa: E402
from handicapper.engine import load_config                # noqa: E402

CFG_PATH = os.path.join(ROOT, "rules_config.json")
FIX = os.path.join(HERE, "fixtures", "racing_dudes_sample.html")


class TestTickets(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(SRC.parse_ticket("2,3,7 BOX", 2), ([["2", "3", "7"], ["2", "3", "7"]], True))
        self.assertEqual(SRC.parse_ticket("2,3/2,3,4", 2), ([["2", "3"], ["2", "3", "4"]], False))
        self.assertEqual(SRC.parse_ticket("2,3/2,3,4,7/2,3,4,7", 3), ([["2", "3"], ["2", "3", "4", "7"], ["2", "3", "4", "7"]], False))
        self.assertEqual(SRC.parse_ticket("1A,2 BOX", 2), ([["1A", "2"], ["1A", "2"]], True))
        for bad in ("", None, "2,3/4", "2 BOX", "two,three"):
            self.assertIsNone(SRC.parse_ticket(bad, 2 if bad != "2,3/4" else 3), bad)

    def test_wagers_from_a_run(self):
        from handicapper.pipeline import run_card
        snap = run_card(build_card(), config_path=CFG_PATH, multirace=False, racing_dudes=FIX)["result"]
        W, races = SRC.rd_wagers(snap)
        self.assertEqual(races, {1, 3})
        r1 = [(w["type"], w["legs"], w["box"]) for w in W if w["race_no"] == 1]
        self.assertIn(("WIN", [["6"]], False), r1); self.assertIn(("PLACE", [["6"]], False), r1); self.assertIn(("SHOW", [["6"]], False), r1)
        self.assertIn(("EXACTA", [["1", "6"], ["1", "2", "3", "6"]], False), r1)
        self.assertIn(("TRIFECTA", [["1", "6"], ["1", "2", "3", "6"], ["1", "2", "3", "6"]], False), r1)
        # races 1 and 3 are not consecutive: no double from their Multi Race horses
        self.assertFalse([w for w in W if w["type"] in ("DOUBLE", "PICK3", "PICK4")])
        snap["races"][1]["racing_dudes"] = {"order": ["1"], "wagers": {"multi_race": "1,2"}}
        W2, _ = SRC.rd_wagers(snap)
        self.assertTrue(any(w["type"] == "DOUBLE" and w["races"] == [1, 2] for w in W2))
        self.assertTrue(any(w["type"] == "PICK3" and w["races"] == [1, 2, 3] for w in W2))
        snap["races"][0]["timeform"] = {"power_picks": ["6", "1", "3"]}
        T, tr = SRC.tf_wagers(snap)
        self.assertEqual(tr, {1}); self.assertEqual([(w["type"], w["box"]) for w in T], [("WIN", False), ("EXACTA", True), ("TRIFECTA", True)])

    def test_compare_same_races(self):
        from handicapper.pipeline import run_card
        from handicapper.snapshot import write_snapshot
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, "data", "out")); os.makedirs(os.path.join(tmp, "results"))
            res = run_card(build_card(), config_path=CFG_PATH, multirace=False, racing_dudes=FIX)["result"]
            res["races"][0]["timeform"] = {"power_picks": ["6", "1", "2"]}
            write_snapshot(os.path.join(tmp, "data", "out"), "synth", res, "pre-race")
            with open(os.path.join(tmp, "data", "out", "synth.picks.json"), "w", encoding="utf-8") as fh:
                json.dump(res, fh, default=str)
            results = {"track": "Del Mar", "date": res["date"], "races": [
                {"race_no": 1, "finish": ["6", "1", "2", "3"], "win": 14.0, "place": {"6": 6.0, "1": 3.2}, "show": {"6": 4.0, "1": 2.6, "2": 2.4},
                 "exotics": [{"type": "EXACTA", "base": 1.0, "combo": "6-1", "payout": 30.0}, {"type": "TRIFECTA", "base": 0.5, "combo": "6-1-2", "payout": 60.0}]},
                {"race_no": 3, "finish": ["2", "4", "5"], "win": 9.0, "place": {"2": 4.0, "4": 3.0}, "show": {"2": 3.0, "4": 2.4, "5": 2.2}}]}
            with open(os.path.join(tmp, "results", "synth.results.json"), "w", encoding="utf-8") as fh:
                json.dump(results, fh)
            c = SRC.compare(tmp, load_config(CFG_PATH))
            rd, tf = c["sources"]["racing_dudes"], c["sources"]["timeform"]
            self.assertEqual((rd["races"], rd["cards"], tf["races"]), (2, 1, 1))
            self.assertEqual((rd["by_type"]["WIN"]["bets"], rd["by_type"]["WIN"]["won"], rd["by_type"]["WIN"]["ret"]), (2, 1, 14.0))
            self.assertEqual((rd["by_type"]["PLACE"]["ret"], rd["by_type"]["SHOW"]["ret"]), (9.0, 6.4))   # R3's Win pick #4 ran second
            self.assertEqual((rd["by_type"]["EXACTA"]["won"], rd["by_type"]["EXACTA"]["ret"]), (1, 30.0))
            self.assertEqual(tf["by_type"]["EXACTA"]["ret"], 30.0); self.assertEqual(tf["by_type"]["TRIFECTA"]["ret"], 60.0)
            self.assertGreater(rd["engine_total"]["bets"], 0)
            self.assertLessEqual(tf["engine_total"]["bets"], rd["engine_total"]["bets"])   # the engine on race 1 only for Timeform
            txt = SRC.format_compare(c)
            self.assertIn("## Racing Dudes: 2 races on 1 cards", txt); self.assertIn("| **Counted total** |", txt)
            self.assertEqual(SRC.compare(tempfile.mkdtemp(), load_config(CFG_PATH))["sources"]["racing_dudes"]["races"], 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
