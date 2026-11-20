"""Phase C: the tote board.  Normalisation (open and closed pools, coupled entries, late scratch, malformed numbers,
pool mismatch, net vs gross odds), polling policy and credit cap, immutable capture with heartbeats, the HTTP client
against a fake server (failure, 429 with Retry-After, 5xx retry, 401 no retry, malformed body), stale quotes, the
decision marks that alone set price_basis observed, and that a credential never reaches a log or a fixture."""
from __future__ import annotations

import http.server
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ["RACEDESK_WEATHER"] = "off"
os.environ["RACEDESK_TOTE"] = "off"

from carovex import tote as T                                   # noqa: E402
from carovex.ledger import connect, race_id                    # noqa: E402

FIX = os.path.join(HERE, "fixtures", "tote_replay.json")
SECRET = "SECRETKEY_abcdefghijklmnopqrstuvwxyz0123456789"


def fixture():
    with open(FIX, encoding="utf-8") as fh:
        return json.load(fh)


def board_at(at: str, race_no: int = 1, **kw) -> dict:
    prov = T.ReplayToteProvider(fixture(), clock=at)
    resp = prov.board(date="2026-11-06", **kw)
    race = next(r for r in resp["races"] if r["race_number"] == race_no)
    return T.normalise_board(race, prov.now())


class TestNormalise(unittest.TestCase):
    def test_closed_pools_show_the_morning_line_but_no_quote(self):
        b = board_at("2026-11-06T19:40:00Z")
        self.assertEqual((b["status"], b["pools_open"], b["closed"]), ("open", False, False))
        self.assertEqual(b["allocation"], {})
        one = b["interests"]["1"]
        self.assertIsNone(one["odds_to_1"]); self.assertEqual(one["morning_line"], "8/5"); self.assertEqual(one["ml_decimal"], 2.6)
        self.assertEqual(b["interests"]["7"]["scratched"], True)
        self.assertEqual(b["win_pool_total"], None)
        self.assertIn("net", b["odds_convention"]["odds_to_1"])

    def test_open_pool_allocation_coupled_entry_and_malformed_numbers(self):
        b = board_at("2026-11-06T20:16:00Z")
        self.assertTrue(b["pools_open"])
        self.assertEqual(b["interests"]["1"]["pgms"], ["1", "1A"])            # one betting interest
        self.assertEqual(b["interests"]["1"]["win_pool"], 4000.0)
        a = b["allocation"]
        self.assertAlmostEqual(sum(a.values()), 1.0, places=5)
        self.assertAlmostEqual(a["1"], 4000.0 / 11500.0, places=5)
        self.assertNotIn("7", a)                                               # scratched: out of the allocation
        self.assertIn("4", a)                                                  # malformed pool counts as 0 but the horse is live
        self.assertTrue(any("malformed win_odds 'abc'" in f for f in b["flags"]))
        self.assertTrue(any("malformed win_pool 'x'" in f for f in b["flags"]))
        self.assertTrue(any("odds missing" in f for f in b["flags"]))
        self.assertEqual(b["reconciliation"]["ok"], True)                      # 11500 == sum
        self.assertEqual((b["interests"]["1"]["odds_to_1"], b["interests"]["1"]["win_decimal"]), (2.0, 3.0))   # net 2-1 vs gross 3.0

    def test_late_scratch_and_pool_total_mismatch(self):
        b = board_at("2026-11-06T20:26:30Z")
        self.assertTrue(b["interests"]["4"]["scratched"]); self.assertEqual(b["interests"]["4"]["scratch_reason"], "Vet")
        self.assertIn("4", b["scratched"]); self.assertNotIn("4", b["allocation"])
        self.assertFalse(b["reconciliation"]["ok"])
        self.assertTrue(any("WIN pool total" in f for f in b["flags"]))
        self.assertAlmostEqual(sum(b["allocation"].values()), 1.0, places=5)

    def test_off_and_official_and_history(self):
        off = board_at("2026-11-06T20:34:00Z")
        self.assertEqual((off["status"], off["closed"], off["final"]), ("off", True, False))
        fin = board_at("2026-11-06T20:41:30Z", history=True, exotics=True)
        self.assertEqual((fin["status"], fin["final"]), ("official", True))
        self.assertEqual(fin["interests"]["2"]["odds_text"], "7/2")
        self.assertEqual(len(fin["history"]), 2); self.assertEqual(fin["exotics"]["probables"][0]["code"], "EX")
        self.assertNotEqual(off["content_hash"], fin["content_hash"])

    def test_odds_conventions(self):
        self.assertEqual(T.odds_to_1("9/1"), 9.0); self.assertEqual(T.odds_to_1("8/5"), 1.6); self.assertEqual(T.odds_to_1("7-2"), 3.5)
        self.assertEqual(T.odds_to_1(2.6), 2.6); self.assertIsNone(T.odds_to_1("abc")); self.assertIsNone(T.odds_to_1(None)); self.assertIsNone(T.odds_to_1("1/0"))
        self.assertEqual(T.interest_key({"number": "1A"}), ("1A", "1")); self.assertEqual(T.interest_key({"number": 12}), ("12", "12"))

    def test_freshness(self):
        b = board_at("2026-11-06T20:16:00Z")
        now = T.parse_iso("2026-11-06T20:16:30Z")
        self.assertEqual(T.freshness(b, now, 120), {"age_seconds": 38, "stale": False})
        self.assertTrue(T.freshness(b, T.parse_iso("2026-11-06T20:30:00Z"), 120)["stale"])
        self.assertEqual(T.secs_to_post(b, now), 810.0)


class TestPolicy(unittest.TestCase):
    def test_intervals(self):
        p = T.PollPlan({"poll": {"from_minutes": 60, "sparse_every": 300, "near_minutes": 15, "near_every": 60, "last_minutes": 5, "last_every": 30}})
        self.assertIsNone(p.interval(61 * 60)); self.assertEqual(p.interval(40 * 60), 300.0); self.assertEqual(p.interval(10 * 60), 60.0)
        self.assertEqual(p.interval(120), 30.0); self.assertEqual(p.interval(-60), 30.0); self.assertIsNone(p.interval(-60, closed=True))

    def test_credit_cap_disables_decisions_and_never_crashes(self):
        tmp = tempfile.mkdtemp()
        try:
            prov = T.ReplayToteProvider(fixture(), clock="2026-11-06T20:16:00Z")
            day = prov.now()
            cl = T.CreditLedger(tmp, cap=4)
            self.assertTrue(cl.can_spend(2, day)); cl.record({"credits_cost": 2}, day); cl.record({"credits_cost": 2}, day); self.assertFalse(cl.can_spend(2, day))
            self.assertEqual(T.CreditLedger(tmp, cap=4).spent(day), 4)       # persisted across processes
            poller = T.TotePoller(tmp, prov, {"tote": {"daily_credit_cap": 4}})
            res = poller.poll("DMR", "2026-11-06")
            self.assertFalse(res["ok"]); self.assertEqual(res["status"]["feed"], "disabled"); self.assertFalse(res["status"]["decisions_enabled"])
            self.assertIn("cap", res["status"]["reason"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestCapture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.prov = T.ReplayToteProvider(fixture(), clock="2026-11-06T19:40:00Z")
        self.poller = T.TotePoller(self.tmp, self.prov, {"tote": {"daily_credit_cap": 100, "heartbeat_minutes": 5}})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_changed_boards_stored_once_unchanged_only_as_heartbeat(self):
        rid = race_id("DMR", "2026-11-06", 1)
        r = self.poller.poll("DMR", "2026-11-06")
        self.assertTrue(r["ok"]); self.assertEqual(set(r["races"]), {1, 2}); self.assertEqual(r["next_in"], 300.0)   # 50 minutes out: sparse reads
        self.assertEqual(len(self.poller.capture.history(rid)), 1)
        self.prov.advance(60); self.poller.poll("DMR", "2026-11-06")            # same board a minute later: not stored
        self.assertEqual(len(self.poller.capture.history(rid)), 1)
        self.prov.advance(5 * 60); self.poller.poll("DMR", "2026-11-06")        # heartbeat after 5 minutes
        h = self.poller.capture.history(rid)
        self.assertEqual([x["kind"] for x in h], ["board", "heartbeat"])
        self.prov.set_clock("2026-11-06T20:16:30Z"); r = self.poller.poll("DMR", "2026-11-06")
        self.assertEqual(r["next_in"], 60.0)                                   # 13.5 minutes to post
        self.prov.set_clock("2026-11-06T20:27:00Z"); r = self.poller.poll("DMR", "2026-11-06")
        self.assertEqual(r["next_in"], 30.0)
        self.prov.set_clock("2026-11-06T20:42:00Z"); r = self.poller.poll("DMR", "2026-11-06", races=[1])
        self.assertIsNone(r["next_in"]); self.assertTrue(r["races"][1]["final"])
        h = self.poller.capture.history(rid)
        self.assertEqual([x["kind"] for x in h], ["board", "heartbeat", "board", "board", "board"])
        self.assertEqual(h[-1]["status"], "official")
        # rows are never updated: the first stored board still reads as it was
        self.assertEqual(h[0]["status"], "open"); self.assertFalse(h[0]["pools_open"])
        files = os.listdir(os.path.join(self.tmp, "data", "private", "tote", "2026-11-06", "tvg_DMR_2026-11-06_1"))
        self.assertEqual(len(files), len(h))                                   # one immutable file per stored observation
        fin = self.poller.final("DMR", "2026-11-06", 1)
        self.assertTrue(fin["ok"]); self.assertIn("history", fin["races"][1])
        self.assertEqual(self.poller.capture.latest(rid)["kind"], "final")

    def test_capture_is_usable_from_another_thread(self):
        import threading
        self.prov.set_clock("2026-11-06T20:16:00Z")
        self.poller.poll("DMR", "2026-11-06")                         # connection created on this thread
        errors = []

        def other():
            try:
                self.prov.set_clock("2026-11-06T20:27:00Z")
                r = self.poller.poll("DMR", "2026-11-06")              # the Desk serves the next request from another thread
                assert r["ok"], r["status"]
                assert self.poller.capture.latest(race_id("DMR", "2026-11-06", 1))["status"] == "open"
            except Exception as e:   # noqa: BLE001
                errors.append(repr(e))
        t = threading.Thread(target=other); t.start(); t.join()
        self.assertEqual(errors, [])

    def test_replayed_rate_limit_is_a_status_not_a_crash(self):
        self.prov.set_clock("2026-11-06T20:21:00Z")
        r = self.poller.poll("DMR", "2026-11-06")
        self.assertFalse(r["ok"]); self.assertEqual(r["status"]["feed"], "error"); self.assertIn("rate_limit", r["status"]["reason"])
        self.assertFalse(r["status"]["decisions_enabled"])


class FakeAPI(http.server.BaseHTTPRequestHandler):
    script: list = []
    seen: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        FakeAPI.seen.append({"path": self.path, "key": self.headers.get("X-API-Key"), "auth": self.headers.get("Authorization")})
        step = FakeAPI.script.pop(0) if FakeAPI.script else (200, {}, json.dumps(fixture()["boards"][1]["response"]))
        status, headers, body = step
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        data = body.encode() if isinstance(body, str) else body
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)


class TestClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def provider(self):
        self.sleeps = []
        return T.PuntersEdgeProvider(key=SECRET, base_url=self.url, timeout=5, max_retries=2, sleep=self.sleeps.append)

    def test_board_sends_the_key_header_and_reads_credit_headers(self):
        FakeAPI.script = [(200, {"X-Credits-Cost": "2", "X-Credits-Remaining": "1490", "X-Ratelimit-Remaining": "29"}, json.dumps(fixture()["boards"][1]["response"]))]
        FakeAPI.seen = []
        b = self.provider().board(date="2026-11-06")
        self.assertEqual(len(b["races"]), 2); self.assertEqual(b["meta"]["credits_cost"], 2); self.assertEqual(b["meta"]["credits_remaining"], 1490)
        self.assertEqual(FakeAPI.seen[0]["key"], SECRET); self.assertIsNone(FakeAPI.seen[0]["auth"])
        self.assertIn("date=2026-11-06", FakeAPI.seen[0]["path"]); self.assertIn("country=US", FakeAPI.seen[0]["path"])

    def test_429_honours_retry_after_then_succeeds(self):
        FakeAPI.script = [(429, {"Retry-After": "3"}, "{}"), (200, {"X-Credits-Cost": "2"}, json.dumps(fixture()["boards"][1]["response"]))]
        b = self.provider().board()
        self.assertEqual(len(b["races"]), 2); self.assertEqual(self.sleeps, [3.0])

    def test_5xx_retries_with_backoff_then_fails_as_server(self):
        FakeAPI.script = [(503, {}, "down"), (503, {}, "down"), (503, {}, "down")]
        with self.assertRaises(T.ToteError) as cm:
            self.provider().board()
        self.assertEqual(cm.exception.kind, "server"); self.assertEqual(len(self.sleeps), 2)

    def test_401_is_not_retried_and_never_shows_the_key(self):
        FakeAPI.script = [(401, {}, json.dumps({"detail": "Invalid API key " + SECRET}))]
        log = logging.getLogger("carovex.tote")
        with self.assertLogs(log, level="DEBUG") as cm:
            log.debug("start")
            with self.assertRaises(T.ToteError) as err:
                self.provider().board()
        self.assertEqual(err.exception.kind, "auth"); self.assertNotIn(SECRET, str(err.exception))
        self.assertNotIn(SECRET, "\n".join(cm.output))
        self.assertEqual(len(FakeAPI.script), 0)

    def test_malformed_body(self):
        FakeAPI.script = [(200, {}, "not json")]
        with self.assertRaises(T.ToteError) as cm:
            self.provider().board()
        self.assertEqual(cm.exception.kind, "malformed")
        FakeAPI.script = [(200, {}, json.dumps({"date": "x"}))]
        with self.assertRaises(T.ToteError):
            self.provider().board()

    def test_connection_failure_is_network(self):
        p = T.PuntersEdgeProvider(key=SECRET, base_url="http://127.0.0.1:9", timeout=1, max_retries=0, sleep=lambda s: None)
        with self.assertRaises(T.ToteError) as cm:
            p.board()
        self.assertEqual(cm.exception.kind, "network"); self.assertNotIn(SECRET, str(cm.exception))

    def test_redaction_and_fixture_carry_no_credential(self):
        self.assertEqual(T.redact(f"X-API-Key: {SECRET} and token {SECRET}"), "X-API-Key: *** and token ***")
        text = open(FIX, encoding="utf-8").read()
        self.assertNotIn(SECRET, text)
        self.assertFalse(re.search(r"(?i)api[-_]?key\"?\s*:\s*\"[A-Za-z0-9]{16,}", text))

    def test_key_from_env_or_private_file(self):
        tmp = tempfile.mkdtemp()
        try:
            os.environ.pop(T.KEY_ENV, None)
            self.assertIsNone(T.read_key(tmp))
            os.makedirs(os.path.join(tmp, "data", "private")); open(os.path.join(tmp, T.KEY_FILE), "w").write("filekey\n")
            self.assertEqual(T.read_key(tmp), "filekey")
            os.environ[T.KEY_ENV] = "envkey"
            self.assertEqual(T.read_key(tmp), "envkey")
        finally:
            os.environ.pop(T.KEY_ENV, None); shutil.rmtree(tmp, ignore_errors=True)


class TestDecisions(unittest.TestCase):
    def test_quote_and_marks(self):
        b = board_at("2026-11-06T20:26:30Z"); b["observation_id"] = "obs1"
        q = T.quote_for(b, [["1A"]])
        self.assertEqual((q["interest"], q["odds_to_1"], q["odds_text"], q["observation_id"]), ("1", 1.8, "9/5", "obs1"))
        self.assertIsNone(T.quote_for(b, [["1"], ["2", "3"]]))                 # exotics have no single quote
        self.assertTrue(T.quote_for(b, [["4"]])["scratched"])
        tmp = tempfile.mkdtemp()
        try:
            con = connect(tmp)
            con.execute("INSERT INTO race VALUES (?,?,?,?,?,?,?,?,?,?,?)", ("DMR|2026-11-06|1", "synth", "DMR", "2026-11-06", 1, "dirt", "1 Mile", None, None, "test", "t"))
            con.execute("INSERT INTO decision VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("dec1", "DMR|2026-11-06|1", None, "snap", "2026-11-06T20:00:00Z", "before", "WIN", '[["1"]]', "WIN #1", 2.0, "1.5", "morning-line", "suggested", "h", "t"))
            con.commit()
            paper = T.mark_decision(tmp, "synth", "dec1", "paper", q, con=con)
            self.assertEqual((paper["status"], paper["price_basis"], paper["in_ledger"]), ("paper", "morning-line", True))
            acc = T.mark_decision(tmp, "synth", "dec1", "accepted", q, note="placed at the window", con=con)
            self.assertEqual((acc["price_basis"], acc["verified_by"]), ("observed", "owner"))
            rows = con.execute("SELECT status, quote_observation_id, verified_by FROM execution WHERE decision_id='dec1' ORDER BY recorded_at_utc").fetchall()
            self.assertEqual([r[0] for r in rows], ["paper", "accepted_verified"]); self.assertEqual(rows[1][1], "obs1"); self.assertEqual(rows[1][2], "owner")
            with self.assertRaises(ValueError):
                T.mark_decision(tmp, "synth", "dec1", "placed", q, con=con)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


class TestDesk(unittest.TestCase):
    """The Desk with a replay provider: refresh stores boards, the payload carries the latest board per race, a
    mark attaches the quote and sets price_basis observed only for accepted."""

    @classmethod
    def setUpClass(cls):
        from synthetic_card import build_card
        from ui.server import Desk
        cls.tmp = tempfile.mkdtemp(prefix="racedesk-tote-")
        shutil.copy(os.path.join(ROOT, "rules_config.json"), os.path.join(cls.tmp, "rules_config.json"))
        os.makedirs(os.path.join(cls.tmp, "data", "out"))
        with open(os.path.join(cls.tmp, "data", "out", "synth.card.json"), "w", encoding="utf-8") as fh:
            json.dump(build_card(), fh)
        cls.prov = T.ReplayToteProvider(fixture(), clock="2026-11-06T20:16:00Z")
        cls.desk = Desk(cls.tmp, tote_provider=cls.prov)
        cls.desk.run("synth")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_refresh_payload_and_marks(self):
        r = self.desk.tote_refresh("synth")
        self.assertEqual(r["status"]["feed"], "ok"); self.assertIn("1", r["races"]); self.assertEqual(r["next_in"], 60.0)
        d = self.desk.payload("synth")
        b = d["tote"]["races"]["1"]
        self.assertTrue(b["pools_open"]); self.assertEqual(b["interests"]["2"]["odds_text"], "5/2"); self.assertIn("freshness", b)
        self.assertNotIn("history", b)
        w = next(w for w in d["picks"]["races"][0]["wagers"] if w["type"] == "WIN")
        did = w["decision"]["id"]
        rec = self.desk.mark_decision("synth", did, "paper")
        self.assertEqual((rec["status"], rec["price_basis"], rec["quote"]["odds_text"]), ("paper", "morning-line", "2/1"))
        d = self.desk.payload("synth")
        w = next(w for w in d["picks"]["races"][0]["wagers"] if w["decision"]["id"] == did)
        self.assertEqual(w["decision"]["status"], "paper"); self.assertEqual(d["decisions"][did]["race_no"], 1)
        rec = self.desk.mark_decision("synth", did, "accepted", note="placed")
        self.assertEqual(rec["price_basis"], "observed"); self.assertEqual(rec["quote"]["observation_id"], b["observation_id"])
        # the snapshot on disk is untouched; the overlay is applied at read time
        raw = json.load(open(os.path.join(self.tmp, "data", "out", "synth.picks.json"), encoding="utf-8"))
        self.assertEqual(next(w for w in raw["races"][0]["wagers"] if w["decision"]["id"] == did)["decision"]["status"], "suggested")
        # a results file: the accepted win bet is never 'passed' and its price basis is observed
        res = {"track": "Del Mar", "date": "2026-11-06", "races": [{"race_no": 1, "finish": ["1", "2", "6", "3"], "win": 6.4, "final_odds": {"1": 2.2}}]}
        with open(os.path.join(self.tmp, "results", "synth.results.json"), "w", encoding="utf-8") as fh:
            json.dump(res, fh)
        d = self.desk.payload("synth")
        row = next(x for x in d["evaluation"]["rows"] if x["race_no"] == 1 and x["type"] == "WIN" and x.get("decision_id") == did)
        self.assertEqual(row["price_basis"], "observed"); self.assertTrue(row.get("placed", True))
        with self.assertRaises(ValueError):
            self.desk.mark_decision("synth", "nope", "paper")
        self.prov.set_clock("2026-11-06T20:21:00Z")
        r = self.desk.tote_refresh("synth")
        self.assertEqual(r["status"]["feed"], "error"); self.assertFalse(r["status"]["decisions_enabled"])
        self.assertEqual(self.desk.payload("synth")["tote"]["status"]["feed"], "error")


class TestKeySource(unittest.TestCase):
    def test_env_file_placeholder_and_precedence(self):
        tmp = tempfile.mkdtemp()
        saved = os.environ.pop(T.KEY_ENV, None)
        try:
            self.assertIsNone(T.key_with_source(tmp)[0]); self.assertIn("none found", T.key_with_source(tmp)[1])
            with open(os.path.join(tmp, ".env"), "w", encoding="utf-8") as fh:
                fh.write("# comment\nPUNTERSEDGE_API_KEY=your-puntersedge-key-here\n")
            k, src = T.key_with_source(tmp)
            self.assertIsNone(k); self.assertIn("placeholder", src)
            with open(os.path.join(tmp, ".env"), "w", encoding="utf-8-sig") as fh:          # Notepad's byte-order mark
                fh.write('PUNTERSEDGE_API_KEY="realkey123"\n')
            self.assertEqual(T.key_with_source(tmp), ("realkey123", ".env"))
            os.environ[T.KEY_ENV] = "envkey"
            self.assertEqual(T.key_with_source(tmp), ("envkey", "environment variable"))
            p = T.PuntersEdgeProvider(root=tmp)
            self.assertEqual((p.key, p.key_source), ("envkey", "environment variable"))
        finally:
            os.environ.pop(T.KEY_ENV, None)
            if saved is not None:
                os.environ[T.KEY_ENV] = saved
            shutil.rmtree(tmp, ignore_errors=True)

    def test_auth_error_names_the_source_not_the_key(self):
        FakeAPI.script = [(401, {}, "{}")]
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            tmp = tempfile.mkdtemp()
            with open(os.path.join(tmp, ".env"), "w", encoding="utf-8") as fh:
                fh.write(f"PUNTERSEDGE_API_KEY={SECRET}\n")
            saved = os.environ.pop(T.KEY_ENV, None)
            p = T.PuntersEdgeProvider(root=tmp, base_url=f"http://127.0.0.1:{srv.server_address[1]}", max_retries=0, sleep=lambda s: None)
            with self.assertRaises(T.ToteError) as cm:
                p.board()
            self.assertIn("key source: .env", str(cm.exception)); self.assertNotIn(SECRET, str(cm.exception))
            if saved is not None:
                os.environ[T.KEY_ENV] = saved
            shutil.rmtree(tmp, ignore_errors=True)
        finally:
            srv.shutdown()
