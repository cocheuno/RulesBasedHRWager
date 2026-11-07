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
