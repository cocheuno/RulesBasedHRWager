"""One synthetic end-to-end run (offline, deterministic): two mock cards, reconcile the sources, replay several tote
states, freeze paper decisions, close, ingest results, evaluate without hindsight, read the Analysis JSON."""
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

from synthetic_card import build_card                  # noqa: E402
from ui.server import Desk                             # noqa: E402
from carovex import tote as T                          # noqa: E402
from handicapper.identity import reconcile             # noqa: E402
from handicapper.engine import load_config             # noqa: E402
from timeform_pp.reader import parse_lines             # noqa: E402

FIX = os.path.join(HERE, "fixtures", "tote_replay.json")


class TestEndToEnd(unittest.TestCase):
    def test_two_cards_through_the_day(self):
        tmp = tempfile.mkdtemp(prefix="racedesk-e2e-")
        try:
            shutil.copy(os.path.join(ROOT, "rules_config.json"), os.path.join(tmp, "rules_config.json"))
            os.makedirs(os.path.join(tmp, "data", "out")); os.makedirs(os.path.join(tmp, "results"))
            card_a = build_card()
            card_b = copy.deepcopy(card_a); card_b["track"], card_b["track_code"] = "Belmont Park", "BEL"
            for r in card_b["races"]:
                for h in r["horses"]:
                    h["records"]["track_code"] = "BEL"
            for name, card in (("dmr1106y", card_a), ("bel1106y", card_b)):
                with open(os.path.join(tmp, "data", "out", f"{name}.card.json"), "w", encoding="utf-8") as fh:
                    json.dump(card, fh)
            prov = T.ReplayToteProvider(json.load(open(FIX, encoding="utf-8")), clock="2026-11-06T19:40:00Z")
            desk = Desk(tmp, tote_provider=prov)
            # 1. pre-race runs on both cards (the clock is a label; these runs are before post)
            da = desk.run("dmr1106y"); db = desk.run("bel1106y")
            self.assertEqual(da["picks"]["run"]["kind"], "pre-race"); self.assertEqual(db["picks"]["track_code"], "BEL")
            self.assertTrue(all(w["research"]["decision"] in ("NO_BET", "CANDIDATE") for r in da["picks"]["races"] for w in r["wagers"]))
            # 2. reconcile the sources for card A: a Timeform text layer with a program change, and the changes page
            tf = parse_lines(["DEL MAR 11/06/2026", "RACE X", "1 3Õ 6 F", "11/06/2026 1:00 PM 80 Claiming Dirt"] +
                             [f"{'9' if h['pgm'] == '5' else h['pgm']} {h['name']} Colt | Age 4 | Mar | KY-bred Top {80 - i} Fig" for i, h in enumerate(card_a["races"][0]["horses"])])
            rec = reconcile(card_a, timeform=tf, cfg=load_config(os.path.join(tmp, "rules_config.json")))
            self.assertEqual(rec["races"][0]["program_changes"][0]["card_pgm"], "5")
            self.assertEqual(rec["missing"]["timeform"][:2], [2, 3])
            # 3. tote: closed pools, open, a replayed 429, a late scratch, off, official
            states = []
            for clock in ("2026-11-06T19:40:00Z", "2026-11-06T20:16:00Z", "2026-11-06T20:21:00Z", "2026-11-06T20:27:00Z", "2026-11-06T20:34:00Z", "2026-11-06T20:42:00Z"):
                prov.set_clock(clock)
                r = desk.tote_refresh("dmr1106y")
                states.append((r["status"]["feed"], (r["races"].get("1") or {}).get("status")))
            self.assertEqual([s[0] for s in states], ["ok", "ok", "error", "ok", "ok", "ok"])
            self.assertEqual([s[1] for s in states if s[1]], ["open", "open", "open", "off", "official"])
            # 4. freeze a paper decision while the market is open (at the 20:27 board), then the market closes
            prov.set_clock("2026-11-06T20:27:30Z"); desk.tote_refresh("dmr1106y")
            d = desk.payload("dmr1106y")
            win = next(w for w in d["picks"]["races"][0]["wagers"] if w["type"] == "WIN")
            paper = desk.mark_decision("dmr1106y", win["decision"]["id"], "paper")
            self.assertEqual(paper["status"], "paper"); self.assertIsNotNone(paper["quote"]["observation_id"])
            prov.set_clock("2026-11-06T20:42:00Z"); desk.tote_refresh("dmr1106y")
            self.assertTrue(desk.payload("dmr1106y")["tote"]["races"]["1"]["final"])
            # 5. results arrive; the paper decision keeps its frozen quote; evaluation has no hindsight
            r1 = d["picks"]["races"][0]; live = [s for s in r1["sheets"] if not s["eliminated"] and not s["flags"]]
            results = {"track": "Del Mar", "date": "2026-11-06", "races": [
                {"race_no": 1, "finish": [live[1]["pgm"], live[0]["pgm"], live[2]["pgm"]], "win": 7.2, "final_odds": {live[0]["pgm"]: 1.2, live[1]["pgm"]: 2.6},
                 "place": {live[1]["pgm"]: 4.0, live[0]["pgm"]: 2.4}, "show": {live[1]["pgm"]: 3.0, live[0]["pgm"]: 2.1, live[2]["pgm"]: 4.4}, "track_condition": "FAST", "source": "chart", "off_at": "12:33"}]}
            with open(os.path.join(tmp, "results", "dmr1106y.results.json"), "w", encoding="utf-8") as fh:
                json.dump(results, fh)
            d = desk.payload("dmr1106y")
            self.assertEqual(d["decisions"][win["decision"]["id"]]["status"], "paper")
            row = next(x for x in d["evaluation"]["rows"] if x.get("decision_id") == win["decision"]["id"])
            self.assertIn(row["price_basis"], ("assumed-final", "unpriced"))      # paper is not accepted: no observed basis
            pre = d["pre_race"]
            self.assertIsNotNone(pre); self.assertEqual(pre["backtest"]["summary"]["races"], 1)
            # 6. the Analysis JSON: legacy roll-up plus the calibration panel and the data watch
            a = desk.analysis()
            self.assertIsNotNone(a["rollup"]); self.assertEqual(a["evaluation"]["races"], 1)
            self.assertEqual(a["evaluation"]["data_watch"]["gates"]["global_calibration"]["have"], 1)
            self.assertEqual(a["evaluation"]["data_watch"]["gates"]["odds_drift"]["have"], 1)   # the final board with history was stored
            self.assertTrue(all(s["status"].startswith("DEFERRED") for s in a["evaluation"]["deferred"]))
            json.dumps(a, default=str)                                               # serialisable
            bb = desk.best_bets("2026-11-06")
            self.assertEqual({x["card"] for x in bb["bets"]} <= {"dmr1106y", "bel1106y"}, True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
