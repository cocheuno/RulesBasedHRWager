"""Racing Dudes saved picks page: read in its own markup, merged under its own namespace, scored as a benchmark."""
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

from synthetic_card import build_card                                                    # noqa: E402
from racing_dudes.reader import benchmark, format_benchmark, is_racing_dudes, merge_racing_dudes, parse_page, track_day   # noqa: E402
from handicapper.engine import format_report, load_config                                # noqa: E402
from handicapper.pipeline import run_card                                                # noqa: E402
from handicapper.results import backtest, format_backtest                                # noqa: E402

FIX = os.path.join(HERE, "fixtures", "racing_dudes_sample.html")
CFG_PATH = os.path.join(ROOT, "rules_config.json")


def page():
    return open(FIX, "rb").read()


class TestReader(unittest.TestCase):
    def test_parse(self):
        self.assertTrue(is_racing_dudes(page())); self.assertFalse(is_racing_dudes(b"<html>other</html>"))
        d = parse_page(page(), "sample.html")
        self.assertEqual([(t["tid"], t["name"], sorted(t["days"])) for t in d["tracks"]],
                         [("85043", "Del Mar", ["2026-11-06", "2026-11-07"]), ("85028", "Churchill Downs", ["2026-11-06"])])
        r1 = d["tracks"][0]["days"]["2026-11-06"][1]
        self.assertEqual((r1["class_text"], r1["post_time"], r1["distance_text"], r1["surface"]), ("Maiden Claiming", "1:00 pm PST", "1 Mile", "Dirt"))
        self.assertEqual(r1["order"], ["6", "1", "3", "2"]); self.assertEqual([p["role"] for p in r1["picks"]], ["Win", "Place", "Show", "Next Best"])
        self.assertEqual((r1["picks"][0]["name"], r1["picks"][0]["ml"], r1["picks"][0]["jockey"], r1["picks"][0]["trainer"]), ("Second Timer", "6-1", "A Rider", "B Trainer"))
        self.assertEqual(r1["wagers"], {"exacta": "1,6/1,2,3,6", "trifecta": "1,6/1,2,3,6/1,2,3,6", "multi_race": "1,6"})
        self.assertTrue(r1["best_value"]); self.assertFalse(r1["likely_winner"])
        r3 = d["tracks"][0]["days"]["2026-11-06"][3]
        self.assertTrue(r3["likely_winner"]); self.assertEqual(r3["surface"], "Turf")
        self.assertEqual(d["tracks"][1]["days"]["2026-11-06"][1]["order"][0], "1A")          # program letters kept
        cfg = load_config(CFG_PATH)
        self.assertEqual(sorted(track_day(d, "2026-11-06", "DMR", None, cfg)), [1, 3])
        self.assertEqual(sorted(track_day(d, "2026-11-06", None, "Churchill Downs", cfg)), [1])
        self.assertIsNone(track_day(d, "2026-11-06", "GP", None, cfg)); self.assertIsNone(track_day(d, "2026-11-08", "DMR", None, cfg))

    def test_merge_and_name_guard(self):
        card = build_card()
        d = parse_page(page())
        races = track_day(d, card["date"], "DMR", None, load_config(CFG_PATH))
        races[3]["picks"][3]["name"] = "Somebody Else"                                       # #9 on the card is Turf Returner
        notes = merge_racing_dudes(card, races, "sample.html")
        r1, r3 = card["races"][0], card["races"][2]
        self.assertEqual(r1["racing_dudes"]["order"], ["6", "1", "3", "2"])
        self.assertEqual(next(h for h in r1["horses"] if h["pgm"] == "6")["racing_dudes"], {"role": "Win", "rank": 1, "ml": "6-1", "source": "racing_dudes"})
        self.assertEqual(r3["racing_dudes"]["order"], ["4", "5", "1"])                       # the mismatched #9 is left out
        self.assertTrue(any("Somebody Else" in n for n in notes))
        self.assertIsNone(card["races"][1]["racing_dudes"]); self.assertTrue(any("R2: not in the Racing Dudes page" in n for n in notes))
        self.assertEqual(merge_racing_dudes(build_card(), None), ["no Racing Dudes picks for this track and date"])


class TestPipelineAndBacktest(unittest.TestCase):
    def test_no_score_changes_and_benchmark(self):
        base = run_card(build_card(), config_path=CFG_PATH, multirace=False)["result"]
        out = run_card(build_card(), config_path=CFG_PATH, multirace=False, racing_dudes=FIX)
        res = out["result"]
        self.assertIn("racing_dudes", res["run"]["data_sources"])
        for a, b in zip(base["races"], res["races"]):
            self.assertEqual(a["picks"], b["picks"]); self.assertEqual([s["score"] for s in a["sheets"]], [s["score"] for s in b["sheets"]])
        r1 = res["races"][0]
        self.assertEqual(r1["racing_dudes"]["order"], ["6", "1", "3", "2"])
        self.assertEqual(next(s for s in r1["sheets"] if s["pgm"] == "6")["racing_dudes"]["role"], "Win")
        self.assertNotIn("racing_dudes", next(s for s in r1["sheets"] if s["pgm"] == "6")["features"])
        self.assertIn("Racing Dudes (benchmark, not read by any rule): Win #6 / Place #1 / Show #3 / Next Best #2 · Best Value.", format_report(res, detail=1))
        results = {"track": "Del Mar", "date": "2026-11-06", "races": [{"race_no": 1, "finish": ["6", "1", "2"], "win": 14.0},
                                                                        {"race_no": 3, "finish": ["2", "4", "5"], "win": 9.0}]}
        bt = backtest(res, results)
        s = bt["summary"]
        self.assertEqual((s["rd_races"], s["rd_pick_wins"], s["rd_top4"], s["rd_likely_winner"], s["rd_likely_winner_wins"]), (2, 1, 1, 1, 0))
        self.assertIn("Racing Dudes benchmark over 2 races: their win pick won 1", format_backtest(bt))
        labels = {(a["kind"], a["label"]): a for a in bt["angles"]}
        self.assertEqual(labels[("racing_dudes", "Win pick")]["fired"], 2); self.assertEqual(labels[("racing_dudes", "Likely Winner")]["won"], 0)


class TestSnapshotOrder(unittest.TestCase):
    def test_same_second_runs_keep_their_order(self):
        from handicapper.snapshot import list_snapshots, write_snapshot
        tmp = tempfile.mkdtemp()
        try:
            for i in range(3):
                write_snapshot(tmp, "x", {"run": {"at_utc": "2026-11-06T18:00:00Z"}, "races": [], "tag": i}, "pre-race")
            files = [s["file"] for s in list_snapshots(tmp, "x")]
            self.assertEqual(files, ["20261106T180000Z_pre-race.picks.json", "20261106T180000Z_pre-race-2.picks.json", "20261106T180000Z_pre-race-3.picks.json"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestDeskAndBenchmark(unittest.TestCase):
    def test_upload_applies_by_date_and_benchmark_reads_results(self):
        from ui.server import Desk
        tmp = tempfile.mkdtemp(prefix="racedesk-rd-")
        try:
            shutil.copy(CFG_PATH, os.path.join(tmp, "rules_config.json")); os.makedirs(os.path.join(tmp, "data", "out")); os.makedirs(os.path.join(tmp, "results"))
            a = build_card(); b = json.loads(json.dumps(a)); b["track"], b["track_code"] = "Churchill Downs", "CD"
            for name, card in (("dmr1106y", a), ("cdx1106y", b)):
                with open(os.path.join(tmp, "data", "out", f"{name}.card.json"), "w", encoding="utf-8") as fh:
                    json.dump(card, fh)
            desk = Desk(tmp); desk.run("dmr1106y"); desk.run("cdx1106y")
            with self.assertRaises(ValueError):
                desk.save_upload("dmr1106y", "racingdudes", "x.html", b"<html>not it</html>")
            res = desk.save_upload("dmr1106y", "racingdudes", "Dashboard - Racing Dudes.html", page())
            self.assertEqual(res["race_dates"], ["2026-11-06", "2026-11-07"])
            self.assertEqual(sorted(res["files"]), [os.path.join("data", "pps", "racingdudes_2026-11-06.html"), os.path.join("data", "pps", "racingdudes_2026-11-07.html")])
            self.assertEqual({x["card"]: x["races"] for x in res["applied"]}, {"dmr1106y": 2, "cdx1106y": 1})
            self.assertTrue(desk.files("dmr1106y")["racing_dudes"].endswith("racingdudes_2026-11-06.html"))
            d = desk.run("dmr1106y")
            self.assertEqual(d["picks"]["races"][0]["racing_dudes"]["order"], ["6", "1", "3", "2"])
            self.assertEqual(d["roster"][0]["racing_dudes"]["order"], ["6", "1", "3", "2"])
            with open(os.path.join(tmp, "results", "dmr1106y.results.json"), "w", encoding="utf-8") as fh:
                json.dump({"track": "Del Mar", "date": "2026-11-06", "races": [{"race_no": 1, "finish": ["6", "1", "2"], "win": 14.0}]}, fh)
            a2 = desk.analysis()
            self.assertEqual((a2["benchmark"]["rd_races"], a2["benchmark"]["rd_wins"]), (1, 1))
            self.assertEqual(a2["evaluation"]["data_watch"]["gates"]["racing_dudes_value"]["have"], 1)
            bm = benchmark(tmp, parse_page(page()))
            self.assertEqual((bm["races"], bm["rd_pick_wins"], bm["rd_top4"]), (1, 1, 1))
            self.assertIn("their win pick won 1", format_benchmark(bm))
            self.assertIn("No races", format_benchmark(benchmark(tempfile.mkdtemp(), parse_page(page()))))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
