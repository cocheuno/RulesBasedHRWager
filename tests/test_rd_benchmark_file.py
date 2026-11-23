"""Racing Dudes' benchmark is the newest page loaded for the date, whenever it was loaded: no rule reads it, so a
page loaded late cannot carry a result into the engine's picks.  The engine's pre-race runs keep the copy they were
made with; the comparisons read data/out/<card>.racingdudes.json.  A page that lacks a track the saved copy for a
date has (a dashboard showing tomorrow for a few tracks) does not replace that date's page."""
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
from racing_dudes.reader import bench_path, load_card_benchmark, parse_page              # noqa: E402
from handicapper.results import backtest, load_results                                   # noqa: E402
from handicapper.snapshot import list_snapshots, pre_race_by_race                        # noqa: E402

FIX = os.path.join(HERE, "fixtures", "racing_dudes_sample.html")
CFG_PATH = os.path.join(ROOT, "rules_config.json")


def full_page() -> bytes:
    return open(FIX, "rb").read()


def early_page() -> bytes:
    """The morning version: Del Mar race 1's Win and Place swapped, and no tickets yet."""
    s = full_page().decode("utf-8")
    a, b = 'num-6">6</span> Second Timer', 'num-1">1</span> Dropping Dream'
    s = s.replace(a, "@@").replace(b, a).replace("@@", b)
    s = s.replace("<strong>Exacta</strong><br />1,6/1,2,3,6", "<strong>Exacta</strong><br />")
    s = s.replace("<strong>Trifecta</strong><br />1,6/1,2,3,6/1,2,3,6", "<strong>Trifecta</strong><br />")
    return s.encode("utf-8")


def del_mar_only_page() -> bytes:
    """A page without Churchill Downs (another day's dashboard that shows only some tracks for this date)."""
    lines = full_page().decode("utf-8").split("\n")
    return "\n".join(l for l in lines if "85028" not in l).encode("utf-8")


class TestNewestPageIsTheBenchmark(unittest.TestCase):
    def setUp(self):
        from ui.server import Desk
        self.tmp = tempfile.mkdtemp(prefix="racedesk-rdb-")
        shutil.copy(CFG_PATH, os.path.join(self.tmp, "rules_config.json"))
        os.makedirs(os.path.join(self.tmp, "data", "out")); os.makedirs(os.path.join(self.tmp, "results"))
        a = build_card(); b = json.loads(json.dumps(a)); b["track"], b["track_code"] = "Churchill Downs", "CD"
        for name, card in (("dmr1106y", a), ("cdx1106y", b)):
            with open(os.path.join(self.tmp, "data", "out", f"{name}.card.json"), "w", encoding="utf-8") as fh:
                json.dump(card, fh)
        self.desk = Desk(self.tmp)
        self.out = os.path.join(self.tmp, "data", "out")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def results(self):
        p = os.path.join(self.tmp, "results", "dmr1106y.results.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"track": "Del Mar", "date": "2026-11-06", "races": [{"race_no": 1, "finish": ["1", "6", "2"], "win": 6.0},
                                                                            {"race_no": 3, "finish": ["4", "5", "1"], "win": 5.0}]}, fh)
        return load_results(p)

    def test_later_page_replaces_the_benchmark_not_the_run(self):
        self.desk.save_upload("dmr1106y", "racingdudes", "early.html", early_page())
        self.desk.run("dmr1106y")                                            # the pre-race run, made with the morning page
        self.assertEqual(load_card_benchmark(self.out, "dmr1106y")["races"]["1"]["order"], ["1", "6", "3", "2"])
        res = self.results()
        before = pre_race_by_race(self.out, "dmr1106y", res)
        self.assertEqual(backtest(before, res)["summary"]["rd_pick_wins"], 2, "the morning page's win pick #1 won race 1")

        self.desk.save_upload("dmr1106y", "racingdudes", "Dashboard - Racing Dudes.html", full_page())   # loaded after the races
        bench = load_card_benchmark(self.out, "dmr1106y")
        self.assertEqual(bench["file"], "Dashboard - Racing Dudes.html")
        self.assertEqual(bench["races"]["1"]["order"], ["6", "1", "3", "2"])
        after = pre_race_by_race(self.out, "dmr1106y", res)
        r1 = after["races"][0]
        self.assertEqual(r1["racing_dudes"]["order"], ["6", "1", "3", "2"])
        self.assertEqual(r1["racing_dudes"]["wagers"]["exacta"], "1,6/1,2,3,6", "the newest page's tickets")
        self.assertTrue(r1["racing_dudes"]["benchmark_file"])
        self.assertEqual(next(s for s in r1["sheets"] if s["pgm"] == "6")["racing_dudes"]["role"], "Win")
        self.assertEqual(next(s for s in r1["sheets"] if s["pgm"] == "1")["racing_dudes"]["role"], "Place")
        self.assertEqual(backtest(after, res)["summary"]["rd_pick_wins"], 1, "scored on the newest page")
        self.assertEqual(after["racing_dudes_benchmark"]["races"], 2)
        for x, y in zip(before["races"], after["races"]):                   # the engine is untouched
            self.assertEqual(x["picks"], y["picks"]); self.assertEqual([s["score"] for s in x["sheets"]], [s["score"] for s in y["sheets"]])
        snap = json.load(open(list_snapshots(self.out, "dmr1106y")[-1]["path"], encoding="utf-8"))
        self.assertEqual(snap["races"][0]["racing_dudes"]["order"], ["1", "6", "3", "2"], "the run keeps the copy it was made with")
        pl = self.desk.payload("dmr1106y")                                   # the card view shows the benchmark too
        self.assertEqual(pl["picks"]["races"][0]["racing_dudes"]["order"], ["6", "1", "3", "2"])
        self.assertEqual(pl["pre_race"]["backtest"]["summary"]["rd_pick_wins"], 1)

    def test_unchanged_picks_are_not_rewritten(self):
        self.desk.run("dmr1106y")
        self.desk.save_upload("dmr1106y", "racingdudes", "a.html", full_page())
        first = load_card_benchmark(self.out, "dmr1106y")
        self.desk.save_upload("dmr1106y", "racingdudes", "b.html", full_page())
        self.assertEqual(load_card_benchmark(self.out, "dmr1106y"), first)

    def test_a_page_lacking_a_track_keeps_the_dates_page(self):
        self.desk.run("dmr1106y"); self.desk.run("cdx1106y")
        self.desk.save_upload("dmr1106y", "racingdudes", "full.html", full_page())
        res = self.desk.save_upload("dmr1106y", "racingdudes", "partial.html", del_mar_only_page())
        self.assertEqual(res["kept"], [{"date": "2026-11-06", "missing": ["Churchill Downs"]}])
        self.assertEqual(res["files"], [os.path.join("data", "pps", "racingdudes_2026-11-07.html")], "11-07 had only Del Mar: replaced")
        day = parse_page(open(os.path.join(self.tmp, "data", "pps", "racingdudes_2026-11-06.html"), "rb").read())
        self.assertIn("Churchill Downs", [t["name"] for t in day["tracks"]], "Churchill keeps its picks for the date")
        self.assertEqual(load_card_benchmark(self.out, "cdx1106y")["races"]["1"]["order"], ["1A", "2", "3", "4"])
        self.assertEqual({x["card"] for x in res["applied"]}, {"dmr1106y"}, "Del Mar's benchmark is still this page's")

    def test_a_card_read_after_the_page_gets_its_file_on_the_first_run(self):
        self.desk.run("dmr1106y")
        self.desk.save_upload("dmr1106y", "racingdudes", "full.html", full_page())
        os.remove(bench_path(self.out, "cdx1106y"))                          # as if its PPs were read after the upload
        self.desk.run("cdx1106y")
        self.assertEqual(load_card_benchmark(self.out, "cdx1106y")["races"]["1"]["order"], ["1A", "2", "3", "4"])


if __name__ == "__main__":
    unittest.main()
