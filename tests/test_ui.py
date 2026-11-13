"""Race Day Desk server: the Desk class and the HTTP API, on a temporary data folder with the synthetic card."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from synthetic_card import build_card          # noqa: E402
from ui.server import Desk, make_server, parse_multipart, reparse_reason   # noqa: E402


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="racedesk-")
        shutil.copy(os.path.join(ROOT, "rules_config.json"), os.path.join(cls.tmp, "rules_config.json"))
        os.makedirs(os.path.join(cls.tmp, "data", "out"))
        with open(os.path.join(cls.tmp, "data", "out", "synth.card.json"), "w", encoding="utf-8") as fh:
            json.dump(build_card(), fh)
        cls.desk = Desk(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestDesk(Base):
    def test_cards_run_results_process_analysis(self):
        cards = self.desk.cards()
        self.assertEqual([c["card"] for c in cards], ["synth"])
        self.assertFalse(cards[0]["has_picks"])
        pl = self.desk.run("synth", "1:2, 2:1")
        self.assertTrue(pl["picks"] and pl["files"]["picks_json"])
        self.assertEqual(pl["state"]["scratches"], "1:2, 2:1")
        self.assertEqual(pl["picks"]["scratches"], "1:2, 2:1", "picks.json records the scratches it was run with")
        self.assertTrue(any(n.startswith("scratch: R2: scratched #1") for n in pl["picks"]["run_notes"]))
        self.assertEqual(len(pl["roster"][0]["horses"]), 7, "roster keeps scratched horses")
        r2 = next(r for r in pl["picks"]["races"] if r["race_no"] == 2)
        self.assertNotIn("1", [s["pgm"] for s in r2["sheets"]], "scratched horse is not scored")
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "data", "out", "synth.picks.md")))
        pl = self.desk.save_result("synth", {"race_no": 2, "finish": ["3", "5", "4"], "win": "8.00", "place": {"3": "4.20"},
                                             "exotics": [{"type": "exacta", "base": "1", "combo": "3/5", "payout": "26.50"}]})
        self.assertEqual(pl["results"]["races"][0]["finish"], ["3", "5", "4"])
        self.assertEqual(pl["results"]["races"][0]["exotics"][0]["type"], "EXACTA")
        self.assertIsNotNone(pl["backtest"])
        self.assertTrue(any(x["race_no"] == 2 for x in pl["evaluation"]["rows"]))
        # a chart-style result whose runner list omits #7 (Tag Virgin) in R2 -> process re-scores as run
        pl = self.desk.save_result("synth", {"race_no": 2, "finish": ["3", "5", "4"], "win": "8.00"})
        import json as _json
        rp = os.path.join(self.tmp, "results", "synth.results.json")
        data = _json.load(open(rp))
        for r in data["races"]:
            if r["race_no"] == 2:
                r["runners"] = [{"pgm": p, "name": ""} for p in ("1", "2", "3", "4", "6")]
                r["source"] = "chart"
        _json.dump(data, open(rp, "w"))
        self.assertEqual(self.desk.chart_scratches("synth"), "2:5, 2:7")
        pl = self.desk.process("synth")
        self.assertIn("2:7", pl["state"]["scratches"])
        self.assertTrue(any(a["step"] == "As-run re-score" for a in pl["state"]["activity"]))
        r2 = next(r for r in pl["picks"]["races"] if r["race_no"] == 2)
        self.assertNotIn("7", [s["pgm"] for s in r2["sheets"]])
        self.assertIn("Back-test", pl["report"])
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "results", "synth.backtest.md")))
        an = self.desk.analysis()
        self.assertEqual(an["cards"][0]["card"], "synth")
        self.assertEqual([c["track"] for c in an["rollup"]["chart"]], ["DMR", "ALL"])
        self.assertTrue(an["rules"])

    def test_snapshots_are_append_only_and_labelled(self):
        import glob, time
        from handicapper.snapshot import list_snapshots, latest_snapshot, write_snapshot
        tmp = tempfile.mkdtemp(prefix="racedesk-snap-")          # a fresh card: no results on file yet
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy(os.path.join(ROOT, "rules_config.json"), os.path.join(tmp, "rules_config.json"))
        os.makedirs(os.path.join(tmp, "data", "out"))
        with open(os.path.join(tmp, "data", "out", "synth.card.json"), "w", encoding="utf-8") as fh:
            json.dump(build_card(), fh)
        d = Desk(tmp)
        d.run("synth", "")
        time.sleep(1.1)
        d.run("synth", "4:6")                                  # a second pre-race run: a second file, first untouched
        snaps = list_snapshots(d.out, "synth")
        pre = [s for s in snaps if s["kind"] == "pre-race"]
        self.assertGreaterEqual(len(pre), 2)
        self.assertEqual(pre[-1]["scratches"], "4:6")
        first = open(pre[0]["path"], encoding="utf-8").read()
        d.save_result("synth", {"race_no": 2, "finish": ["3", "5", "4"], "win": "8.00"})
        time.sleep(1.1)
        pl = d.run("synth", "4:6")                             # after a result is on file: post-results, not pre-race
        self.assertEqual(pl["state"]["runs"][-1]["kind"], "post-results")
        self.assertEqual(open(pre[0]["path"], encoding="utf-8").read(), first, "an earlier snapshot is never rewritten")
        self.assertEqual(latest_snapshot(d.out, "synth", "pre-race")["scratches"], "4:6")
        snap = latest_snapshot(d.out, "synth", "pre-race")
        self.assertNotIn("features", snap["races"][0]["sheets"][0], "snapshots drop the bulky features")
        self.assertTrue(snap["run"]["at_utc"].endswith("Z") and snap["run"]["config_hash"])
        self.assertEqual(snap["run"]["results_known"], [])
        self.assertTrue(pl["pre_race"], "payload scores the pre-race snapshot once results exist")
        self.assertEqual(pl["pre_race"]["snapshot"]["kind"], "pre-race")
        self.assertEqual(pl["picks"]["run"]["results_known"], [2])
        # process: the as-run re-score is its own kind; the report has both sections
        rp = os.path.join(tmp, "results", "synth.results.json")
        data = json.load(open(rp))
        for r in data["races"]:
            if r["race_no"] == 2:
                r["runners"] = [{"pgm": p, "name": ""} for p in ("1", "2", "3", "4", "6")]
                r["source"] = "chart"
        json.dump(data, open(rp, "w"))
        time.sleep(1.1)
        pl = d.process("synth")
        self.assertEqual(pl["latest_kind"], "as-run")
        self.assertIn("## Pre-race prediction, as bet", pl["report"])
        self.assertIn("## As-run re-score", pl["report"])
        self.assertIn("cannot change", pl["report"])
        kinds = [s["kind"] for s in list_snapshots(d.out, "synth")]
        self.assertEqual(kinds[-1], "as-run")
        self.assertIn("pre-race", kinds)
        with self.assertRaises(ValueError):
            write_snapshot(d.out, "synth", pl["picks"], "guess")
        an = d.analysis()
        self.assertEqual(next(c for c in an["cards"] if c["card"] == "synth")["basis"], "pre-race")

    def test_result_edit_keeps_chart_fields(self):
        tmp = tempfile.mkdtemp(prefix="racedesk-edit-"); self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy(os.path.join(ROOT, "rules_config.json"), os.path.join(tmp, "rules_config.json"))
        os.makedirs(os.path.join(tmp, "data", "out")); os.makedirs(os.path.join(tmp, "results"))
        with open(os.path.join(tmp, "data", "out", "synth.card.json"), "w", encoding="utf-8") as fh:
            json.dump(build_card(), fh)
        chart = {"race_no": 2, "finish": ["3", "5", "4", "1"], "win": 8.0, "place": {"3": 4.2}, "show": {}, "source": "chart",
                 "final_odds": {"3": 3.0, "5": 0.8}, "runners": [{"pgm": "3", "name": "A"}, {"pgm": "5", "name": "B"}],
                 "track_condition": "FAST", "exotics": [{"type": "EXACTA", "base": 1.0, "combo": "3/5", "payout": 26.5}],
                 "ocr": {"source": "chart", "warnings": [], "names": ["A", "B"], "confidence": 1.0}}
        json.dump({"track": "Del Mar", "date": "2026-11-06", "races": [chart]}, open(os.path.join(tmp, "results", "synth.results.json"), "w"))
        d = Desk(tmp)
        d.run("synth", "")
        pl = d.save_result("synth", {"race_no": 2, "finish": ["3", "5", "4", "1"], "win": "8.20", "place": {"3": "4.20"},
                                     "exotics": [{"type": "exacta", "base": "1", "combo": "3/5", "payout": "26.50"}]})
        r = next(x for x in pl["results"]["races"] if x["race_no"] == 2)
        self.assertEqual(r["win"], 8.2, "the corrected field changed")
        self.assertEqual(r["final_odds"], {"3": 3.0, "5": 0.8}, "chart data survives the edit")
        self.assertEqual(len(r["runners"]), 2); self.assertEqual(r["track_condition"], "FAST"); self.assertEqual(r["source"], "chart")
        self.assertEqual(r["corrections"][0]["fields"], ["win"]); self.assertEqual(r["corrections"][0]["original_source"], "chart")
        # a new race entered by hand is marked manual, no correction record
        pl = d.save_result("synth", {"race_no": 5, "finish": ["1", "2", "3"], "win": "3.60"})
        r5 = next(x for x in pl["results"]["races"] if x["race_no"] == 5)
        self.assertEqual(r5["source"], "manual"); self.assertNotIn("corrections", r5)

    def test_pp_upload_refused_for_another_day_or_track(self):
        """The Belmont 11/12 PP dropped on the Churchill 11/11 card (an actual mistake) must be refused."""
        tmp = tempfile.mkdtemp(prefix="racedesk-guard-"); self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy(os.path.join(ROOT, "rules_config.json"), os.path.join(tmp, "rules_config.json"))
        os.makedirs(os.path.join(tmp, "data", "out"))
        with open(os.path.join(tmp, "data", "out", "synth.card.json"), "w", encoding="utf-8") as fh:
            json.dump(build_card(), fh)
        d = Desk(tmp)
        d.run("synth", "")                                          # the card now has picks: it is a record
        d.pp_identity = lambda data: {"track": "Belmont Park", "track_code": "BEL", "date": "2026-11-12"}
        with self.assertRaises(ValueError) as cm:
            d.save_upload("synth", "pp", "bel1112y.pdf", b"%PDF")
        self.assertIn("refused", str(cm.exception)); self.assertIn("2026-11-12", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(tmp, "data", "pps", "synth.pdf")), "nothing written")
        self.assertTrue(os.path.exists(os.path.join(tmp, "data", "out", "synth.card.json")), "cache kept")
        card = build_card()
        d.pp_identity = lambda data: {"track": card["track"], "track_code": card["track_code"], "date": card["date"]}
        out = d.save_upload("synth", "pp", "synth.pdf", b"%PDF")   # the same card's PPs again: fine
        self.assertTrue(out["saved"].endswith("synth.pdf"))
        out = d.save_upload("fresh01", "pp", "x.pdf", b"%PDF")     # a card with no record yet: no check needed
        self.assertTrue(out["saved"].endswith("fresh01.pdf"))

    def test_reparse_reason(self):
        import time
        from brisnet_pp.parser import PARSER_VERSION
        d = os.path.join(self.tmp, "rp"); os.makedirs(d, exist_ok=True)
        pdf, cj = os.path.join(d, "x.pdf"), os.path.join(d, "x.card.json")
        open(pdf, "wb").write(b"%PDF")
        self.assertIsNone(reparse_reason(None, cj), "no PDF: nothing to re-read from")
        self.assertEqual(reparse_reason(pdf, None), "no cached card")
        json.dump({"races": []}, open(cj, "w"))
        self.assertTrue(reparse_reason(pdf, cj).startswith("parser changed (unstamped"))
        json.dump({"races": [], "parser_version": "0.0"}, open(cj, "w"))
        self.assertIn("0.0 -> " + PARSER_VERSION, reparse_reason(pdf, cj))
        json.dump({"races": [], "parser_version": PARSER_VERSION}, open(cj, "w"))
        self.assertIsNone(reparse_reason(pdf, cj), "current stamp, PDF older: keep the cache")
        os.utime(pdf, (time.time() + 60, time.time() + 60))
        self.assertEqual(reparse_reason(pdf, cj), "PDF is newer than the cached card")

    def test_upload_and_multipart(self):
        body = (b"--XX\r\nContent-Disposition: form-data; name=\"card\"\r\n\r\nabc1107y\r\n"
                b"--XX\r\nContent-Disposition: form-data; name=\"kind\"\r\n\r\npng\r\n"
                b"--XX\r\nContent-Disposition: form-data; name=\"file\"; filename=\"r3.png\"\r\nContent-Type: image/png\r\n\r\n\x89PNGdata\r\n--XX--\r\n")
        fields, files = parse_multipart(body, "multipart/form-data; boundary=XX")
        self.assertEqual(fields, {"card": "abc1107y", "kind": "png"})
        self.assertEqual(files[0]["filename"], "r3.png")
        out = self.desk.save_upload("abc1107y", "png", "r3.png", files[0]["data"])
        self.assertTrue(out["saved"].endswith(os.path.join("abc1107y", "r3.png")))
        self.assertEqual(self.desk.files("abc1107y")["pngs"], ["r3.png"])
        out = self.desk.save_upload("abc1107y", "sheet", "x.pdf", b"%PDF")
        self.assertTrue(out["saved"].endswith("abc1107q.pdf"))
        out = self.desk.save_upload("abc1107y", "chart", "20261107ABCUSA4.pdf", b"%PDF")
        self.assertTrue(out["saved"].replace("\\", "/").endswith("abc1107y/r4.pdf"))
        self.assertEqual(self.desk.files("abc1107y")["charts"], ["r4.pdf"])
        with self.assertRaises(ValueError):
            self.desk.save_upload("../bad", "pp", "x.pdf", b"")


class TestHTTP(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.srv = make_server(cls.tmp, port=0)
        cls.port = cls.srv.server_address[1]
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        super().tearDownClass()

    def req(self, path, method="GET", body=None, ctype="application/json"):
        data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method, headers={"Content-Type": ctype})
        with urllib.request.urlopen(r) as resp:
            return resp.status, resp.read()

    def test_shutdown_endpoint(self):
        srv = make_server(self.tmp, port=0)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        r = urllib.request.Request(f"http://127.0.0.1:{port}/api/shutdown", data=b"{}", method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(r) as resp:
            self.assertTrue(json.loads(resp.read())["stopping"])
        t.join(5)
        self.assertFalse(t.is_alive(), "serve_forever returned after /api/shutdown")
        srv.server_close()

    def test_status_endpoint(self):
        import ui.server as srv
        st, b = self.req("/api/status"); d = json.loads(b)
        self.assertFalse(d["code_changed"]); self.assertEqual(d["changed_files"], []); self.assertTrue(d["parser_version"])
        saved = dict(srv.CODE_AT_START)
        try:
            srv.CODE_AT_START["ui/server.py"] -= 100          # pretend the running code is older than the file
            st, b = self.req("/api/status"); d = json.loads(b)
            self.assertTrue(d["code_changed"]); self.assertIn("ui/server.py", d["changed_files"])
        finally:
            srv.CODE_AT_START.clear(); srv.CODE_AT_START.update(saved)

    def test_api_round_trip(self):
        st, b = self.req("/"); self.assertEqual(st, 200); self.assertIn(b"Race Day Desk", b)
        st, b = self.req("/app.js"); self.assertEqual(st, 200)
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/app.js") as resp:
            self.assertEqual(resp.headers.get("Cache-Control"), "no-store")
        st, b = self.req("/api/cards"); self.assertEqual(json.loads(b)[0]["card"], "synth")
        st, b = self.req("/api/cards/synth/run", "POST", {"scratches": ""})
        pl = json.loads(b); self.assertTrue(pl["picks"])
        st, b = self.req("/api/cards/synth/scratches", "PUT", {"scratches": "4:6"})
        self.assertEqual(json.loads(b)["scratches"], "4:6")
        st, b = self.req("/api/cards/synth"); self.assertEqual(json.loads(b)["state"]["scratches"], "4:6")
        st, b = self.req("/api/cards/synth/results", "POST", {"race_no": 5, "finish": ["1", "2", "3"], "win": "3.60"})
        self.assertEqual(json.loads(b)["results"]["races"][-1]["race_no"], 5)
        st, b = self.req("/api/analysis"); self.assertIn("rollup", json.loads(b))
        body = b"--B\r\nContent-Disposition: form-data; name=\"card\"\r\n\r\nsynth\r\n--B\r\nContent-Disposition: form-data; name=\"kind\"\r\n\r\npng\r\n--B\r\nContent-Disposition: form-data; name=\"file\"; filename=\"r5.png\"\r\n\r\nPNG\r\n--B--\r\n"
        st, b = self.req("/api/upload", "POST", body, "multipart/form-data; boundary=B")
        self.assertEqual(json.loads(b)["saved"][0].replace("\\", "/"), "data/results-png/synth/r5.png")
        st, b = self.req("/png/synth/r5.png"); self.assertEqual(b, b"PNG")


if __name__ == "__main__":
    unittest.main()
