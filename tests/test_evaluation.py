"""Phase E: prospective evaluation and the data watch.  Races are the unit; chronological splits; gates count,
never fit; deferred models refuse to fit until their gate is met."""
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

from synthetic_card import build_card                      # noqa: E402
from handicapper import evaluation as EV                   # noqa: E402
from handicapper.deferred import DeferredNotEnoughProspectiveData, OddsDriftForecast, ConditionalLogitRaceModel, statuses   # noqa: E402
from handicapper.engine import load_config                 # noqa: E402

CFG_PATH = os.path.join(ROOT, "rules_config.json")


def rec(date, race_no, winner, model, market=None, track="DMR", **kw):
    r = {"card": f"{track.lower()}{date[5:7]}{date[8:10]}y", "track": track, "date": date, "race_no": race_no, "winner": winner,
         "field_size": len(model), "live": len(model), "surface": "dirt", "condition": "fast", "pace_shape": "honest", "confidence": "high",
         "clock": "after-cutoff", "predicted_at_utc": None, "model": model, "market": market, "blend": model, "final_market": market,
         "has_final_odds": market is not None, "has_timeform": False, "has_tote_history": False, "top_pick": max(model, key=model.get),
         "top_pick_won": max(model, key=model.get) == winner}
    r.update(kw)
    return r


class TestMetrics(unittest.TestCase):
    def test_log_loss_floor_and_brier(self):
        v = {"1": 0.7, "2": 0.3, "3": 0.0}
        self.assertAlmostEqual(EV.log_loss(v, "1", 0.001), -__import__("math").log(0.7 / 1.001), places=4)
        self.assertLess(EV.log_loss(v, "3", 0.001), 7.0)                 # the floor keeps a zero-probability winner finite
        self.assertAlmostEqual(EV.brier(v, "1"), 0.09 + 0.09 + 0.0, places=6)
        m = EV.metrics([rec("2026-11-07", 1, "1", v), rec("2026-11-07", 2, "2", v)], "model", 0.001)
        self.assertEqual((m["races"], m["top_prob_hits"]), (2, 1)); self.assertAlmostEqual(m["uniform_log_loss"], __import__("math").log(3), places=4)
        self.assertIsNone(EV.metrics([], "model", 0.001))

    def test_reliability_wilson_bootstrap(self):
        rs = [rec("2026-11-07", i, "1" if i % 2 else "2", {"1": 0.5, "2": 0.3, "3": 0.2}) for i in range(1, 21)]
        rel = EV.reliability(rs, "model")
        self.assertEqual(sum(b["horses"] for b in rel), 60); self.assertEqual(sum(b["wins"] for b in rel), 20)
        top = next(b for b in rel if b["bin"].startswith("0.40")); self.assertEqual((top["horses"], top["wins"]), (20, 10))
        self.assertEqual(EV.wilson(10, 20), [0.2993, 0.7007]); self.assertIsNone(EV.wilson(0, 0))
        ci = EV.bootstrap_ci(rs, "model", 0.001, 200, 1)
        self.assertEqual(ci, EV.bootstrap_ci(rs, "model", 0.001, 200, 1))        # deterministic
        self.assertLessEqual(ci["top_hit_95"][0], 0.5); self.assertGreaterEqual(ci["top_hit_95"][1], 0.5)
        self.assertIsNone(EV.bootstrap_ci(rs[:3], "model", 0.001, 10, 1))
        self.assertEqual(EV.market_gap(rs, "model"), None)                       # no final market
        rs2 = [rec("2026-11-07", 1, "1", {"1": 0.5, "2": 0.5}, {"1": 0.6, "2": 0.4})]
        self.assertEqual(EV.market_gap(rs2, "model")["mean_abs_gap"], 0.1)
        self.assertEqual([EV.field_bucket(n) for n in (4, 6, 9, 12)], ["<=5", "6-7", "8-9", "10+"])
        self.assertEqual([EV.furlongs_from_text(t) for t in ("6 Furlongs", "6 1/2 Furlongs", "1 Mile", "1 Mile 70 Yards", "1 1/16 Miles", "About 7½ Furlongs", None, "odd")],
                         [6.0, 6.5, 8.0, 8.32, 8.5, 7.5, None, None])
        self.assertEqual([EV.distance_bucket(f) for f in (6.0, 8.0, None)], ["sprint (<8f)", "route (8f+)", "?"])

    def test_candidate_blends_split_chronologically(self):
        rs = []
        for i in range(20):
            d = f"2026-11-{1 + i:02d}"
            rs.append(rec(d, 1, "1" if i < 10 else "2", {"1": 0.6, "2": 0.4}, {"1": 0.3, "2": 0.7}))
        b = EV.candidate_blends(rs, [0.0, 0.5, 1.0], 0.001)
        self.assertEqual((b["early_races"], b["late_races"], b["split_date"]), (10, 10, "2026-11-11"))
        self.assertEqual(b["chosen_on_early"], 0.0)                                # the model is right early ...
        late = {r["ml_weight"]: r["late_log_loss"] for r in b["rows"]}
        self.assertGreater(late[0.0], late[1.0])                                   # ... and wrong late: the honest report says so
        self.assertIn("not changed", b["note"])
        self.assertEqual(EV.candidate_blends(rs[:5], [0.0], 0.001)["rows"], [])


class TestWatch(unittest.TestCase):
    def test_gates_count_and_defer(self):
        rs = [rec("2026-11-07", i, "1", {"1": 0.6, "2": 0.4}, track="DMR" if i % 2 else "BEL") for i in range(1, 31)]
        rs[0]["has_tote_history"] = True; rs[1]["has_timeform"] = True; rs[2]["clock"] = "before-cutoff"
        w = EV.data_watch(rs, {"data_watch": {"gates": {"global_calibration": {"threshold": 300}, "track_specific": {"threshold": 400},
                                                           "odds_drift": {"threshold": 150}, "timeform_value": {"threshold": 200}}}})
        self.assertEqual((w["races"], w["races_before_cutoff"], w["per_track"]), (30, 1, {"BEL": 15, "DMR": 15}))
        g = w["gates"]
        self.assertEqual((g["global_calibration"]["have"], g["global_calibration"]["short_by"], g["global_calibration"]["status"]), (30, 270, EV.DEFERRED))
        self.assertEqual((g["odds_drift"]["have"], g["timeform_value"]["have"], g["track_specific"]["have"]), (1, 1, 15))   # DMR and BEL are on different circuits
        self.assertEqual(g["track_specific"]["per_track"]["DMR"]["status"], EV.DEFERRED)
        self.assertEqual(g["track_specific"]["group"], "circuit"); self.assertIn("pooling assumption", g["track_specific"]["basis"])
        self.assertEqual(g["track_specific"]["per_circuit"]["SoCal"], {"have": 15, "tracks": {"DMR": 15}, "status": EV.DEFERRED})
        # the circuit pools tracks that share a horse population: Saratoga races count with Belmont's
        rs2 = rs + [rec("2026-11-08", i, "1", {"1": 0.6, "2": 0.4}, track="SAR") for i in range(1, 11)]
        for r in rs2:
            r["circuit"] = EV.circuit_of(r["track"], None)
        w3 = EV.data_watch(rs2, None)
        self.assertEqual(w3["gates"]["track_specific"]["per_circuit"]["NYRA"], {"have": 25, "tracks": {"BEL": 15, "SAR": 10}, "status": EV.DEFERRED})
        self.assertEqual(w3["gates"]["track_specific"]["have"], 25)
        self.assertEqual(EV.circuit_of("OP", None), "OP")                       # an unlisted track is its own circuit
        self.assertEqual(EV.circuit_of("kee", {"circuits": {"Kentucky": ["CD", "KEE"]}}), "Kentucky")
        w4 = EV.data_watch(rs2, {"data_watch": {"gates": {"track_specific": {"group": "track"}}}})   # the owner can switch back to tracks
        self.assertEqual(w4["gates"]["track_specific"]["have"], 15); self.assertEqual(w4["gates"]["track_specific"]["group"], "track")
        w2 = EV.data_watch(rs, {"data_watch": {"gates": {"global_calibration": {"threshold": 20}}}})   # the owner lowers a threshold
        self.assertEqual(w2["gates"]["global_calibration"]["status"], EV.READY)
        self.assertEqual(w2["gates"]["odds_drift"]["threshold"], 150)              # others keep the defaults
        txt = EV.format_watch(w)
        self.assertIn("DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA", txt); self.assertIn("| global_calibration |", txt); self.assertIn("the code only counts", txt)

    def test_deferred_models_refuse_until_the_gate_is_met(self):
        w = EV.data_watch([], None)
        with self.assertRaises(DeferredNotEnoughProspectiveData) as cm:
            OddsDriftForecast(w).fit([])
        self.assertIn("0 of 150 odds_drift", str(cm.exception)); self.assertEqual(cm.exception.gate, "odds_drift")
        st = statuses(w)
        self.assertEqual(len(st), 6); self.assertTrue(all(s["status"] == EV.DEFERRED for s in st))
        w["gates"]["global_calibration"]["status"] = EV.READY
        with self.assertRaises(NotImplementedError):                                # met: still an owner decision
            ConditionalLogitRaceModel(w).fit([])


class TestRecords(unittest.TestCase):
    def test_records_from_snapshots_and_results(self):
        from handicapper.pipeline import run_card
        from handicapper.snapshot import write_snapshot
        tmp = tempfile.mkdtemp()
        try:
            cfg = load_config(CFG_PATH, "DMR")
            card = build_card()
            out_dir = os.path.join(tmp, "data", "out"); os.makedirs(os.path.join(tmp, "results")); os.makedirs(out_dir)
            res = run_card(card, config_path=CFG_PATH, multirace=False)["result"]
            res["run"]["kind"] = "pre-race"
            write_snapshot(out_dir, "synth", res, "pre-race")
            with open(os.path.join(out_dir, "synth.picks.json"), "w", encoding="utf-8") as fh:
                json.dump(res, fh, default=str)
            r1 = res["races"][0]; live = [s for s in r1["sheets"] if not s["eliminated"] and not s["flags"]]
            results = {"track": "Del Mar", "date": card["date"], "races": [
                {"race_no": 1, "finish": [live[0]["pgm"], live[1]["pgm"], live[2]["pgm"]], "win": 5.0, "final_odds": {s["pgm"]: 3.0 for s in live}, "track_condition": "FAST", "source": "chart", "off_at": "12:33"},
                {"race_no": 2, "finish": ["2", "1", "3"], "win": 9.0, "track_condition": "FAST"},
                {"race_no": 3, "finish": ["99"]}]}                                  # a winner not on the card: skipped
            with open(os.path.join(tmp, "results", "synth.results.json"), "w", encoding="utf-8") as fh:
                json.dump(results, fh)
            recs = EV.race_records(tmp, load_config(CFG_PATH))
            self.assertEqual([r["race_no"] for r in recs], [1, 2])
            self.assertEqual(recs[0]["track"], "DMR"); self.assertTrue(recs[0]["has_final_odds"]); self.assertFalse(recs[1]["has_final_odds"])
            self.assertEqual((recs[0]["circuit"], recs[0]["distance"], recs[1]["distance"]), ("SoCal", "route (8f+)", "sprint (<8f)"))
            self.assertTrue(recs[0]["top_pick_won"]); self.assertEqual(recs[0]["condition"], "fast")
            self.assertAlmostEqual(sum(recs[0]["model"].values()), 1.0, places=5); self.assertAlmostEqual(sum(recs[0]["final_market"].values()), 1.0, places=5)
            self.assertIn(recs[0]["clock"], ("before-cutoff", "after-cutoff", "unknown"))
            ev = EV.evaluate(tmp, load_config(CFG_PATH))
            self.assertEqual(ev["races"], 2); self.assertEqual(ev["data_watch"]["gates"]["global_calibration"]["have"], 2)
            self.assertIn("model", ev["compare"]); self.assertEqual(ev["compare"]["final_market"]["races"], 1)
            txt = EV.format_evaluation(ev)
            self.assertIn("# Prospective evaluation: 2 races", txt); self.assertIn("Data watch", txt); self.assertIn("hindsight", txt)
            self.assertIn("## By distance", txt); self.assertIn("## By circuit", txt); self.assertIn("Circuit gate: SoCal 2 (DMR 2)", txt)
            self.assertEqual(load_config(CFG_PATH)["circuits"]["NYRA"], ["BEL", "SAR", "AQU"])
            self.assertEqual(load_config(CFG_PATH)["data_watch"]["gates"]["track_specific"]["group"], "circuit")   # the file's gates reach the evaluation
            self.assertIn("circuit", ev["data_watch"]["gates"]["track_specific"]["unit"])
            empty = EV.evaluate(tempfile.mkdtemp(), load_config(CFG_PATH))
            self.assertEqual(empty["races"], 0); self.assertIsNone(empty["compare"]["model"])
            self.assertIn("0 of 300", str(DeferredNotEnoughProspectiveData("global_calibration", 0, 300, "x")))
            EV.format_evaluation(empty)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
