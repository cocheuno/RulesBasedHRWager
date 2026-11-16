"""Phase F Desk additions: the scratch set compared with the last run, the weather text box round trip, the market
history endpoint, best bets of the day as a labelled view, the .env loader."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ["RACEDESK_WEATHER"] = "off"; os.environ["RACEDESK_TOTE"] = "off"

from synthetic_card import build_card                  # noqa: E402
from ui.server import Desk, load_env_file, make_server  # noqa: E402
from carovex import tote as T                          # noqa: E402

FIX = os.path.join(HERE, "fixtures", "tote_replay.json")


class TestDeskF(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="racedesk-f-")
        shutil.copy(os.path.join(ROOT, "rules_config.json"), os.path.join(cls.tmp, "rules_config.json"))
        os.makedirs(os.path.join(cls.tmp, "data", "out"))
        with open(os.path.join(cls.tmp, "data", "out", "synth.card.json"), "w", encoding="utf-8") as fh:
            json.dump(build_card(), fh)
        cls.prov = T.ReplayToteProvider(json.load(open(FIX, encoding="utf-8")), clock="2026-11-06T20:16:00Z")
        cls.desk = Desk(cls.tmp, tote_provider=cls.prov)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_last_run_scratches_in_payload(self):
        d = self.desk.payload("synth")
        self.assertIsNone(d["last_run_scratches"])                     # no run yet
        d = self.desk.run("synth", scratches="1:4")
        self.assertEqual(d["last_run_scratches"], "1:4")
        st = self.desk.state("synth"); st["scratches"] = "1:4, 2:6"; self.desk.save_state(st)   # ticked one more, not re-run
        d = self.desk.payload("synth")
        self.assertEqual((d["state"]["scratches"], d["last_run_scratches"]), ("1:4, 2:6", "1:4"))   # the Desk compares these two

    def test_weather_text_box_round_trip(self):
        w = self.desk.save_weather("synth", "Light Rain\nWind NW at 13 mph\tTemperature 44°F\nHumidity 82%")
        o = w["observation"]
        self.assertEqual((o["provenance"], o["condition"], o["wind_direction"], o["wind_mph"], o["temperature_f"], o["humidity_pct"]), ("manual", "Light Rain", "NW", 13.0, 44.0, 82))
        d = self.desk.payload("synth")
        self.assertTrue(any(x["provenance"] == "manual" for x in d["state"]["weather"]))

    def test_market_history_and_best_bets(self):
        self.desk.run("synth")
        self.desk.tote_refresh("synth")
        self.prov.set_clock("2026-11-06T20:27:00Z"); self.desk.tote_refresh("synth")
        h = self.desk.tote_history("synth", 1)
        self.assertEqual(h["race_no"], 1); self.assertGreaterEqual(len(h["reads"]), 2)
        self.assertEqual(h["reads"][0]["status"], "open"); self.assertIn("2", h["reads"][-1]["odds"])
        self.assertEqual(self.desk.tote_history("synth", 9)["reads"], [])
        bb = self.desk.best_bets("2026-11-06")
        self.assertIn("labelled view", bb["label"]); self.assertIn("12 of 45", bb["label"])
        self.assertTrue(1 <= len(bb["bets"]) <= 2)
        for x in bb["bets"]:
            self.assertEqual(x["card"], "synth"); self.assertIsNotNone(x["ev_at_ml"]); self.assertIsNotNone(x["min_odds"])
        self.assertEqual(self.desk.best_bets("2020-01-01")["bets"], [])

    def test_env_loader(self):
        p = os.path.join(self.tmp, ".env")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("# comment\nRACEDESK_TEST_ONE=alpha\nRACEDESK_WEATHER=should-not-win\nEMPTY=\n")
        os.environ.pop("RACEDESK_TEST_ONE", None)
        got = load_env_file(p)
        self.assertEqual(got, {"RACEDESK_TEST_ONE": "alpha"})          # existing variables win; empty values are skipped
        self.assertEqual(os.environ["RACEDESK_WEATHER"], "off")
        os.environ.pop("RACEDESK_TEST_ONE", None)
        self.assertEqual(load_env_file(os.path.join(self.tmp, "missing.env")), {})
        example = open(os.path.join(ROOT, ".env.example"), encoding="utf-8").read()
        self.assertIn("PUNTERSEDGE_API_KEY=", example); self.assertNotRegex(example, r"PUNTERSEDGE_API_KEY=[A-Za-z0-9]{24,}")


class TestHTTPF(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="racedesk-fh-")
        shutil.copy(os.path.join(ROOT, "rules_config.json"), os.path.join(cls.tmp, "rules_config.json"))
        os.makedirs(os.path.join(cls.tmp, "data", "out"))
        with open(os.path.join(cls.tmp, "data", "out", "synth.card.json"), "w", encoding="utf-8") as fh:
            json.dump(build_card(), fh)
        cls.srv = make_server(cls.tmp, port=0)
        import threading
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, path):
        with urllib.request.urlopen(self.url + path, timeout=10) as r:
            return json.loads(r.read())

    def post(self, path, body):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    def test_endpoints(self):
        self.post("/api/cards/synth/run", {})
        bb = self.get("/api/best-bets?date=2026-11-06")
        self.assertIn("bets", bb); self.assertIn("labelled view", bb["label"])
        h = self.get("/api/cards/synth/tote/history?race_no=1")
        self.assertEqual(h["reads"], [])
        w = self.post("/api/cards/synth/weather", {"text": "Overcast / Wind SW at 10 mph Temperature 60°F / Humidity 70%"})
        self.assertEqual(w["observation"]["humidity_pct"], 70)
        d = self.get("/api/cards/synth")
        self.assertEqual(d["last_run_scratches"], "")


if __name__ == "__main__":
    unittest.main()
