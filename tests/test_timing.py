"""Phase A: per-race cutoffs by the clock, decision records, the ledger and its time-travel query."""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from synthetic_card import build_card                                                  # noqa: E402
from handicapper.timing import cutoff_status, off_at_utc, post_at_utc, race_cutoffs, timing_summary   # noqa: E402
from handicapper.pipeline import run_card                                              # noqa: E402
from handicapper.snapshot import pre_race_by_race, write_snapshot, list_snapshots      # noqa: E402
from handicapper.wagering import evaluate_wager, make_wager                            # noqa: E402

POSTS = {1: "(12:20)/11:20/10:20/ 9:20", 2: "(12:50)/11:50/10:50/ 9:50", 3: "( 1:19)/12:19/11:19/10:19",
         4: "( 1:48)/12:48/11:48/10:48", 5: "( 2:17)/ 1:17/12:17/11:17", 6: "( 2:47)/ 1:47/12:47/11:47"}


def card_with_posts():
    card = build_card()
    card["date"] = "2026-11-07"                 # the tests' clock times are on this date
    for r in card["races"]:
        r["post_time"] = POSTS.get(r["race_no"])
    return card


class TestClock(unittest.TestCase):
    def test_post_time_is_eastern_whatever_the_track(self):
        self.assertEqual(post_at_utc("2026-11-07", "(12:20)/11:20/10:20/ 9:20").isoformat(), "2026-11-07T17:20:00+00:00")
        self.assertEqual(post_at_utc("2026-11-07", "( 3:18)/ 2:18/ 1:18/12:18").isoformat(), "2026-11-07T20:18:00+00:00")
        self.assertEqual(post_at_utc("2026-11-07", "(10:30)/ 9:30/ 8:30/ 7:30").isoformat(), "2026-11-07T15:30:00+00:00", "10 o'clock is morning")
        self.assertIsNone(post_at_utc("2026-11-07", None))
        self.assertEqual(off_at_utc("2026-11-15", "12:32", "America/Los_Angeles").isoformat(), "2026-11-15T20:32:00+00:00")
        self.assertIsNone(off_at_utc("2026-11-15", "12:32", None), "no timezone, no off time")

    def test_two_races_have_different_cutoffs(self):          # (i)
        card = card_with_posts()
        run_at = datetime(2026, 11, 7, 17, 35, tzinfo=timezone.utc)   # 12:35 ET: after R1 (12:20), before R2 (12:50)
        cut = race_cutoffs("2026-11-07", card["races"], run_at, 2)
        self.assertEqual(cut["1"]["status"], "after-cutoff"); self.assertEqual(cut["2"]["status"], "before-cutoff")
        self.assertNotEqual(cut["1"]["cutoff_at_utc"], cut["2"]["cutoff_at_utc"])
        self.assertEqual(timing_summary(cut)["label"], "mixed")
        # the chart's actual off time beats the scheduled post
        res = {2: {"off_at": "12:33"}}
        cut2 = race_cutoffs("2026-11-07", card["races"], run_at, 2, res, "America/New_York")
        self.assertEqual(cut2["2"]["basis"], "off"); self.assertEqual(cut2["2"]["status"], "after-cutoff")
        self.assertEqual(cutoff_status(run_at, run_at, 0), "before-cutoff"); self.assertEqual(cutoff_status(None, run_at, 2), "unknown")


class TestSnapshotsByTheClock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="carovex-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _snap(self, at_utc, kind="pre-race"):
        out = run_card(card_with_posts(), multirace=False)
        res = out["result"]; res["run"]["at_utc"] = at_utc
        from handicapper.timing import parse_utc
        res["run"]["cutoffs"] = race_cutoffs(res["date"], out["card"]["races"], parse_utc(at_utc), 2)
        for r in res["races"]:
            for w in r["wagers"]:
                w["decision"]["at_utc"] = at_utc; w["decision"]["id"] = w["decision"]["id"][:8] + at_utc[11:16].replace(":", "")
        return write_snapshot(self.tmp, "synth", res, kind)

    def test_after_post_snapshot_is_excluded_even_without_results(self):   # (iv), (vi)
        p1 = self._snap("2026-11-07T16:00:00Z")      # before every race
        p2 = self._snap("2026-11-07T17:55:00Z")      # 12:55 ET: after R1 and R2 (12:20, 12:50); before R3 (1:19)
        comp = pre_race_by_race(self.tmp, "synth", None, None, 2)
        pr = comp["timing"]["per_race"]
        self.assertEqual(pr["1"]["file"], os.path.basename(p1)); self.assertEqual(pr["2"]["file"], os.path.basename(p1))
        self.assertEqual(pr["3"]["file"], os.path.basename(p2), "the newest before-cutoff run wins per race")
        self.assertEqual(comp["timing"]["label"], "verified"); self.assertEqual(comp["timing"]["excluded"], [])
        self.assertEqual(comp["snapshot"]["kind"], "composite")
        # a card first run after R1 went off: R1 is excluded outright, with no result file in sight
        shutil.rmtree(os.path.join(self.tmp, "snapshots")); self._snap("2026-11-07T17:55:00Z")
        comp = pre_race_by_race(self.tmp, "synth", None, None, 2)
        self.assertEqual(comp["timing"]["excluded"], [1, 2]); self.assertNotIn(1, [r["race_no"] for r in comp["races"]])
        # legacy: no post times, no cutoffs, no results -> unverified, newest pre-race snapshot
        shutil.rmtree(os.path.join(self.tmp, "snapshots"))
        lc = build_card(); lc["date"] = "2026-11-07"
        legacy = run_card(lc, multirace=False)["result"]; legacy["run"].pop("cutoffs"); legacy["run"]["at_utc"] = "2026-11-07T23:00:00Z"
        for r in legacy["races"]: r.pop("post_time", None)
        write_snapshot(self.tmp, "synth", legacy, "pre-race")
        comp = pre_race_by_race(self.tmp, "synth", None, None, 2)
        self.assertEqual(comp["timing"]["label"], "unverified")
        # ... but once a chart with an off time exists, even a legacy evening run is judged by the clock
        comp = pre_race_by_race(self.tmp, "synth", {"races": [{"race_no": 1, "off_at": "12:22", "finish": ["1"]}]}, "America/New_York", 2)
        self.assertIn(1, comp["timing"]["excluded"])

    def test_decisions_are_frozen_per_run(self):                       # (ii), (v)
        p1 = self._snap("2026-11-07T16:00:00Z"); before = open(p1, "rb").read()
        d1 = {w["decision"]["id"] for r in json.load(open(p1))["races"] for w in r["wagers"]}
        p2 = self._snap("2026-11-07T16:30:00Z")
        self.assertNotEqual(p1, p2); self.assertEqual(open(p1, "rb").read(), before, "a later run never rewrites an earlier record")
        d2 = {w["decision"]["id"] for r in json.load(open(p2))["races"] for w in r["wagers"]}
        self.assertFalse(d1 & d2, "every run carries its own decision ids")
        self.assertTrue(all(w["decision"]["status"] == "suggested" for r in json.load(open(p2))["races"] for w in r["wagers"]))

    def test_final_odds_cannot_pass_an_accepted_decision(self):       # (iii)
        by = {4: {"race_no": 4, "finish": ["7"], "win": 3.6, "final_odds": {"7": 0.8}}}
        w = make_wager("WIN", [["7"]], race_no=4) | {"min_odds_by": {"7": 1.5}, "decision": {"status": "suggested"}}
        self.assertFalse(evaluate_wager(w, by, 2.0)["placed"], "a suggestion is passed by the assumed final price")
        w["decision"] = {"status": "accepted"}
        r = evaluate_wager(w, by, 2.0)
        self.assertTrue(r["placed"] and r["hit"]); self.assertEqual(r["price_basis"], "observed"); self.assertEqual(r["ret"], 3.6)

    def test_ledger_import_and_time_travel(self):
        from carovex import ledger
        root = self.tmp; os.makedirs(os.path.join(root, "data", "out")); os.makedirs(os.path.join(root, "results"))
        shutil.move(os.path.join(self.tmp, "snapshots"), os.path.join(root, "data", "out", "snapshots")) if os.path.exists(os.path.join(self.tmp, "snapshots")) else None
        out = run_card(card_with_posts(), multirace=False); res = out["result"]; res["run"]["at_utc"] = "2026-11-07T16:00:00Z"
        write_snapshot(os.path.join(root, "data", "out"), "synth", res, "pre-race")
        res2 = copy.deepcopy(res); res2["run"]["at_utc"] = "2026-11-07T18:00:00Z"
        for r in res2["races"]:
            for w in r["wagers"]: w["decision"]["id"] = w["decision"]["id"][::-1]; w["decision"]["at_utc"] = "2026-11-07T18:00:00Z"
        write_snapshot(os.path.join(root, "data", "out"), "synth", res2, "pre-race")
        json.dump({"track": res["track"], "date": res["date"], "races": [{"race_no": 2, "finish": ["1", "3"], "win": 8.0, "source": "chart"}]},
                  open(os.path.join(root, "results", "synth.results.json"), "w"))
        con = ledger.connect(root)
        n1 = ledger.import_card(root, "synth", con); n2 = ledger.import_card(root, "synth", con)
        self.assertEqual(n1["snapshots"], 2); self.assertGreater(n1["decisions"], 0); self.assertEqual(n1["settlements"], 1)
        self.assertEqual((n2["forecasts"], n2["decisions"], n2["settlements"]), (0, 0, 0), "idempotent")
        known = ledger.as_of(root, "synth", 3, "2026-11-07T17:00:00Z")
        self.assertEqual(known["forecast"]["predicted_at_utc"], "2026-11-07T16:00:00Z", "the 18:00 run is in the future")
        self.assertEqual(known["results_known"], [], "the result was received at import time, after the cutoff asked for")
        later = ledger.as_of(root, "synth", 3, "2026-11-07T19:00:00Z")
        self.assertEqual(later["forecast"]["predicted_at_utc"], "2026-11-07T18:00:00Z")
        self.assertTrue(all(d["status"] == "suggested" for d in later["decisions"]))
        self.assertEqual(con.execute("SELECT status FROM execution LIMIT 1").fetchone()[0], "not_submitted")
        self.assertEqual(con.execute("SELECT MAX(version) FROM schema_version").fetchone()[0], ledger.SCHEMA_VERSION)
        con.close()


if __name__ == "__main__":
    unittest.main()
