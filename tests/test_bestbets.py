"""Best bets of the day: one rule for today's list and the record; the record uses the pre-race prediction, so a
re-run after the races cannot change it."""
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

from synthetic_card import build_card                     # noqa: E402
from handicapper import bestbets as BB                    # noqa: E402
from handicapper.engine import load_config                # noqa: E402

CFG_PATH = os.path.join(ROOT, "rules_config.json")


def sheet(pgm, p, ml):
    return {"pgm": pgm, "name": f"H{pgm}", "ml_odds": f"{ml}/1", "ml_decimal": float(ml), "model_prob": p, "win_prob": p}


class TestSelect(unittest.TestCase):
    def test_top_two_by_ev_one_per_horse(self):
        picks = {"races": [
            {"race_no": 1, "sheets": [sheet("1", 0.4, 2), sheet("2", 0.2, 6)], "wagers": [{"type": "WIN", "legs": [["1"]], "min_odds": 1.9},
                                                                                            {"type": "WIN", "legs": [["1"]], "min_odds": 1.9},
                                                                                            {"type": "EXACTA", "legs": [["1"], ["2"]]}]},
            {"race_no": 2, "sheets": [sheet("3", 0.3, 4), sheet("4", 0.1, 20)], "wagers": [{"type": "WIN", "legs": [["3", "4"]], "min_odds_by": {"3": 3.0, "4": 9.0}}]},
            {"race_no": 3, "sheets": [{"pgm": "5", "ml_decimal": None, "model_prob": 0.5}], "wagers": [{"type": "WIN", "legs": [["5"]]}]}]}
        got = BB.select(picks)
        self.assertEqual([(b["race_no"], b["pgm"]) for b in got], [(2, "4"), (2, "3")])     # EV 0.1*21-1 = 1.1, 0.3*5-1 = 0.5 (#1: 0.4*3-1 = 0.2)
        self.assertEqual(got[0]["min_odds"], 9.0)
        self.assertEqual(len(BB.select(picks, per_card=5)), 3)                              # no ML: not a candidate; no duplicate #1


class TestRecord(unittest.TestCase):
    def test_record_from_pre_race_prediction(self):
        from handicapper.pipeline import run_card
        from handicapper.snapshot import write_snapshot
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, "data", "out")); os.makedirs(os.path.join(tmp, "results"))
            res = run_card(build_card(), config_path=CFG_PATH, multirace=False)["result"]
            write_snapshot(os.path.join(tmp, "data", "out"), "synth", res, "pre-race")
            with open(os.path.join(tmp, "data", "out", "synth.picks.json"), "w", encoding="utf-8") as fh:
                json.dump(res, fh, default=str)
            bets = BB.select(res)
            self.assertEqual(len(bets), 2)
            b0, b1 = bets
            races = [{"race_no": b0["race_no"], "finish": [b0["pgm"], "x", "y"], "win": 9.4, "final_odds": {b0["pgm"]: 3.7}},
                     {"race_no": b1["race_no"], "finish": ["x", b1["pgm"], "y"], "win": 5.0, "final_odds": {b1["pgm"]: 0.4}}]
            with open(os.path.join(tmp, "results", "synth.results.json"), "w", encoding="utf-8") as fh:
                json.dump({"track": "Del Mar", "date": res["date"], "races": races}, fh)
            rec = BB.record(tmp, load_config(CFG_PATH))
            self.assertEqual(rec["all"], {"bets": 2, "won": 1, "itm": 2, "cost": 4.0, "return": 9.4, "roi": 1.35})
            self.assertEqual(rec["at_price"]["bets"], 2 if (b1["min_odds"] or 0) <= 0.4 else 1)
            self.assertEqual(rec["by_track"]["DMR"]["won"], 1); self.assertEqual(list(rec["by_date"]), [res["date"]])
            self.assertIn("So far 1 of 2 won (+135% at $2)", BB.summary_line(rec))
            # a later run with results on file (post-results) does not change the record
            res2 = json.loads(json.dumps(res, default=str)); res2["run"]["results_known"] = [1, 2, 3, 4, 5, 6]
            for r in res2["races"]:
                r["wagers"] = []
            write_snapshot(os.path.join(tmp, "data", "out"), "synth", res2, "post-results")
            self.assertEqual(BB.record(tmp, load_config(CFG_PATH))["all"]["bets"], 2)
            self.assertIn("| All | 2 | 1 |", BB.format_record(rec))
            self.assertEqual(BB.record(tempfile.mkdtemp(), load_config(CFG_PATH))["all"]["bets"], 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
