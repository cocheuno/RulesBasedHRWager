"""Phase D: research probabilities, EV and price, NO_BET codes, place and show candidates, and the owner's wager
policy.  Picks and scores are untouched by any of it; only the suggested wagers change where the decisions table says."""
from __future__ import annotations

import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ["RACEDESK_WEATHER"] = "off"; os.environ["RACEDESK_TOTE"] = "off"

from synthetic_card import build_card                                  # noqa: E402
from handicapper import research as RS                                 # noqa: E402
from handicapper.engine import format_report, load_config, score_card, win_price   # noqa: E402
from handicapper.pipeline import run_card                              # noqa: E402
from handicapper.policy import apply_policy, pools_not_offered         # noqa: E402
from handicapper.wagering import evaluate_card                         # noqa: E402
from carovex import tote as T                                          # noqa: E402

CFG_PATH = os.path.join(ROOT, "rules_config.json")
FIX = os.path.join(HERE, "fixtures", "tote_replay.json")


def board(at="2026-11-06T20:26:30Z", race_no=1):
    prov = T.ReplayToteProvider(json.load(open(FIX, encoding="utf-8")), clock=at)
    race = next(r for r in prov.board(date="2026-11-06")["races"] if r["race_number"] == race_no)
    b = T.normalise_board(race, prov.now()); b["freshness"] = T.freshness(b, prov.now(), 120); b["observation_id"] = "obs"
    return b


class TestVectors(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(CFG_PATH, "DMR")
        self.res = score_card(build_card(), self.cfg, multirace=False)
        self.r1 = self.res["races"][0]

    def test_research_vector_sums_to_one_with_floors_for_eliminated(self):
        rv = RS.research_vector(self.r1["sheets"], None, self.cfg["research"])
        p = rv["p_rule_heuristic"]
        self.assertAlmostEqual(sum(p.values()), 1.0, places=3)
        self.assertEqual(rv["problems"], [])
        legal = {s["pgm"] for s in self.r1["sheets"] if not s["flags"]}
        self.assertEqual(set(p), {RS.interest_of(k) for k in legal})           # AE/MTO alternates are not legal starters
        self.assertTrue(all(v > 0 for v in p.values()))                          # every legal starter has mass
        self.assertTrue(rv["eliminated"])                                        # R1 has eliminations
        for k in rv["eliminated"]:
            self.assertLessEqual(p[k], 0.03)                                     # the floor, renormalised
        self.assertEqual(rv["model_status"], "UNTRAINED"); self.assertIsNone(rv["p_final_model"])
        self.assertIsNone(rv["q_live_market"]); self.assertEqual(rv["q_reason"], "no tote board")
        self.assertEqual(rv["anchor_source"], "morning-line")                    # alpha 1, beta 0: the renormalised ML
        self.assertAlmostEqual(sum(rv["p_market_anchor"].values()), 1.0, places=3)

    def test_market_anchor_with_live_tote_and_beta(self):
        b = board("2026-11-06T20:16:00Z")                                        # open, reconciled pools
        rv = RS.research_vector(self.r1["sheets"], b, dict(self.cfg["research"], market_max_age_seconds=10 ** 6))
        self.assertEqual(rv["anchor_source"], "tote")
        self.assertIsNotNone(rv["q_live_market"]); self.assertAlmostEqual(sum(rv["q_live_market"].values()), 1.0, places=3)
        self.assertEqual(rv["p_market_anchor"], rv["q_live_market"])            # beta 0: the anchor is the market
        rv2 = RS.research_vector(self.r1["sheets"], b, dict(self.cfg["research"], beta=1.0, market_max_age_seconds=10 ** 6))
        self.assertNotEqual(rv2["p_market_anchor"], rv2["q_live_market"])
        self.assertAlmostEqual(sum(rv2["p_market_anchor"].values()), 1.0, places=3)
        top = max(rv2["z"], key=rv2["z"].get)
        self.assertGreater(rv2["p_market_anchor"][top], rv2["q_live_market"][top])   # a positive beta tilts towards the engine's top score
        stale = RS.research_vector(self.r1["sheets"], b, self.cfg["research"], now_age_seconds=999)
        self.assertIsNone(stale["q_live_market"]); self.assertIn("old", stale["q_reason"])
        self.assertEqual(RS.research_vector(self.r1["sheets"], board(), self.cfg["research"])["q_reason"], "pool total does not reconcile")
        closed = dict(b, closed=True, final=False)
        self.assertEqual(RS.research_vector(self.r1["sheets"], closed, dict(self.cfg["research"], market_max_age_seconds=10 ** 6))["q_reason"], "market closed")

    def test_vector_checks(self):
        self.assertEqual(RS.check_vector({"1": 0.5, "2": 0.5}), [])
        self.assertIn("sums to 0.900000", RS.check_vector({"1": 0.5, "2": 0.4}))
        self.assertTrue(any("negative" in x for x in RS.check_vector({"1": 1.2, "2": -0.2})))
        self.assertTrue(any("no mass" in x for x in RS.check_vector({"1": 1.0}, legal={"1", "2"})))
        with self.assertRaises(ValueError):
            RS.validate_research({"model_status": "TRAINED"})
        with self.assertRaises(ValueError):
            RS.validate_pricing({"tau": -1})


class TestPrice(unittest.TestCase):
    def test_ev_o_min_break_even(self):
        self.assertEqual(RS.ev(0.25, 4.0), 0.25); self.assertEqual(RS.ev(0.25, 3.0), 0.0); self.assertIsNone(RS.ev(0.0, 3.0))
        self.assertEqual(RS.o_min(0.25, {"tau": 0.15}), 3.6)                      # 1.15 / 0.25 - 1
        self.assertEqual(RS.o_min(0.25, {"tau": 0.15, "costs": 0.05, "rebate": 0.10}), 3.4)
        self.assertEqual(RS.break_even(0.25), 3.0)
        s = RS.scenarios(0.25, 3.5, {"tau": 0.15, "adverse_drift": 0.2})
        self.assertEqual((s["ev_at_quote"], s["adverse_quote_odds"], s["ev_after_drift"], s["quote_meets_o_min"]), (0.125, 2.8, -0.05, False))
        self.assertIn("research diagnostics", s["label"])

    def test_win_price_uses_o_min_not_fair_times_margin(self):
        sel = {"min_ml_for_win_bet": 1.5, "pricing": {"tau": 0.15}}
        w = win_price({"model_prob": 0.25, "fair_odds": 3.0, "ml_decimal": 3.5, "ml_odds": "7/2"}, sel)
        self.assertEqual((w["min_odds"], w["break_even"], w["ok"]), (3.6, 3.0, False))
        self.assertIn("15% return", w["why"])
        w = win_price({"model_prob": 0.25, "fair_odds": 3.0, "ml_decimal": 4.0, "ml_odds": "4/1"}, sel)
        self.assertTrue(w["ok"])
        self.assertEqual(win_price({"model_prob": 0.6, "fair_odds": 0.7, "ml_decimal": 2.0, "ml_odds": "2/1"}, sel)["min_odds"], 1.5)   # floor


class TestGates(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(CFG_PATH, "DMR")
        self.res = score_card(build_card(), self.cfg, multirace=True)
        self.r1 = self.res["races"][0]

    def test_untrained_model_is_no_bet_and_exotics_are_candidates(self):
        RS.attach(self.res, None, self.cfg)
        for r in self.res["races"]:
            self.assertEqual(r["research"]["model_status"], "UNTRAINED")
            for w in r["wagers"]:
                g = w["research"]
                if w["type"] in ("WIN", "PLACE", "SHOW"):
                    self.assertEqual(g["decision"], "NO_BET"); self.assertIn("UNTRAINED_MODEL", g["codes"]); self.assertIn("NO_VALIDATED_EDGE", g["codes"])
                    self.assertIn("STALE_DATA", g["codes"])                        # no quote at all
                else:
                    self.assertEqual((g["decision"], g["label"]), ("CANDIDATE", "candidate, unpriced"))
                self.assertFalse(g["experimental"])
            for s in r["sheets"]:
                self.assertEqual(s["research"]["model_status"], "UNTRAINED"); self.assertIsNone(s["research"]["p_final_model"])
        for key in ("pick3", "pick4"):
            rec = (self.res["multirace"].get(key) or {}).get("recommended")
            if rec:
                self.assertEqual(rec["research"]["label"], "candidate, unpriced")

    def test_gates_with_a_live_board(self):
        b = board(); b["freshness"] = {"age_seconds": 5, "stale": False}
        rv = RS.research_vector(self.r1["sheets"], b, dict(self.cfg["research"], market_max_age_seconds=10 ** 6))
        win = next(w for w in self.r1["wagers"] if w["type"] == "WIN")
        g = RS.gate_wager(win, rv, b, self.cfg["research"], self.cfg["pricing"])
        self.assertEqual(g["decision"], "NO_BET"); self.assertIn("UNTRAINED_MODEL", g["codes"])
        self.assertIn("POOL_UNCERTAINTY", g["codes"])                              # the fixture's pool total does not reconcile
        self.assertIsNotNone(g["diagnostics"]["ev_at_quote"])
        validated = dict(self.cfg["research"], model_status="VALIDATED", market_max_age_seconds=10 ** 6)
        rv2 = RS.research_vector(self.r1["sheets"], b, validated)
        b2 = dict(b, reconciliation={"ok": True}); b2["interests"] = json.loads(json.dumps(b["interests"]))
        g2 = RS.gate_wager(win, rv2, b2, validated, self.cfg["pricing"])
        self.assertNotIn("UNTRAINED_MODEL", g2["codes"]); self.assertNotIn("POOL_UNCERTAINTY", g2["codes"])
        self.assertIn("SCRATCH_OR_COUPLED_MISMATCH", g2["codes"])                 # the board couples 1 and 1A; the card has no 1A
        b2["interests"]["1"]["pgms"] = ["1"]
        g3 = RS.gate_wager(win, rv2, b2, validated, self.cfg["pricing"])
        self.assertTrue({"INSUFFICIENT_PRICE", "NO_VALIDATED_EDGE"} & set(g3["codes"]) or g3["decision"] == "BET")
        # scratched horse, stale board, closed market, unmatched runner
        b2["interests"]["1"]["scratched"] = True
        self.assertIn("SCRATCH_OR_COUPLED_MISMATCH", RS.gate_wager(win, rv2, b2, validated)["codes"])
        self.assertIn("STALE_DATA", RS.gate_wager(win, rv2, dict(b2, freshness={"age_seconds": 999, "stale": True}), validated)["codes"])
        self.assertIn("MARKET_CLOSED", RS.gate_wager(win, rv2, dict(b2, closed=True, final=False), validated)["codes"])
        ghost = dict(win, legs=[["99"]])
        self.assertIn("UNMATCHED_RUNNER", RS.gate_wager(ghost, rv2, b2, validated)["codes"])
        self.assertIn("BANKROLL_CAP", RS.gate_wager(win, rv2, b2, validated, bankroll_ok=False)["codes"])

    def test_pipeline_attaches_research_and_boards(self):
        b = board(); b["freshness"] = {"age_seconds": 5, "stale": False}
        out = run_card(build_card(), config_path=CFG_PATH, multirace=False, boards={1: b})
        r1 = out["result"]["races"][0]
        self.assertIn("research", r1); self.assertIn("research", r1["wagers"][0])
        self.assertIn(r1["research"]["q_reason"], (None, "pool total does not reconcile", "quote is 300s old"))
        self.assertIsNotNone(r1["research"]["p_market_anchor"])


class TestPlaceShow(unittest.TestCase):
    def test_harville_and_candidates(self):
        hv = RS.harville({"1": 0.4, "2": 0.3, "3": 0.2, "4": 0.1})
        self.assertAlmostEqual(sum(v["place"] for v in hv.values()), 2.0, places=3)
        self.assertAlmostEqual(sum(v["show"] for v in hv.values()), 3.0, places=3)
        self.assertGreater(hv["1"]["show"], hv["1"]["place"]); self.assertGreater(hv["1"]["place"], hv["1"]["win"])
        self.assertEqual(RS.min_price_2(0.5, {"place_show_tau": 0.1}), 4.4)
        cfg = load_config(CFG_PATH, "DMR")
        res = score_card(build_card(), cfg, multirace=False)
        for r in res["races"]:
            ps = r["place_show"]
            self.assertEqual((len(ps["place"]), len(ps["show"])), (1, 1))         # at least one of each, every race
            self.assertIsNotNone(ps["place"][0]["min_price_2"])
            live = [s for s in r["sheets"] if not s["eliminated"] and not s["flags"]]
            win_bet = {k for w in r["wagers"] if w["type"] == "WIN" for k in w["legs"][0]}
            expect = live[1]["pgm"] if (live[0]["pgm"] in win_bet and len(live) > 1) else live[0]["pgm"]
            self.assertEqual(ps["place"][0]["pgm"], expect, f"R{r['race_no']}: {ps['note']}")
            self.assertTrue(any(w["type"] == "PLACE" for w in r["wagers"]) and any(w["type"] == "SHOW" for w in r["wagers"]))
            self.assertTrue(any(t.startswith("PLACE #") for t in r["other_wagers"]))
            self.assertIn("heuristic", ps["label"])

    def test_evaluation_settles_place_and_show(self):
        cfg = load_config(CFG_PATH, "DMR")
        res = score_card(build_card(), cfg, multirace=False)
        r1 = res["races"][0]
        pl = next(w for w in r1["wagers"] if w["type"] == "PLACE")["legs"][0][0]
        results = {"track": "Del Mar", "date": "2026-11-06", "races": [
            {"race_no": 1, "finish": ["9", pl, "2", "3"], "win": 9.0, "place": {"9": 4.2, pl: 3.4}, "show": {"9": 3.0, pl: 2.6, "2": 2.2}},
            {"race_no": 5, "finish": ["1", "2", "3"], "win": 2.4, "place": {"1": 2.1, "2": 2.6}, "show": {}, "source": "chart",
             "runners": [{"pgm": "1"}, {"pgm": "2"}, {"pgm": "3"}, {"pgm": "4"}]}]}
        ev = evaluate_card(res, results, cfg["wagering"])
        rows = {(x["race_no"], x["type"]): x for x in ev["rows"]}
        p1, s1 = rows[(1, "PLACE")], rows[(1, "SHOW")]
        self.assertTrue(p1["hit"]); self.assertEqual((p1["unit"], p1["cost"], p1["ret"]), (2.0, 2.0, 3.4)); self.assertEqual(p1["price_basis"], "pool-payout")
        self.assertTrue(s1["hit"]); self.assertEqual(s1["ret"], 2.6)
        s5 = rows[(5, "SHOW")]
        self.assertEqual(s5["status"], "not offered"); self.assertFalse(s5["placed"])
        p5 = rows[(5, "PLACE")]
        self.assertTrue(p5["known"])
        self.assertIn("PLACE", [x["type"] for x in ev["rows"]]); self.assertIn("SHOW", [x["type"] for x in ev["rows"]])
        from handicapper.wagering import rollup
        ru = rollup([ev])
        self.assertIn("PLACE", ru["by_type"]); self.assertIn("SHOW", ru["by_type"])


class TestPolicy(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(CFG_PATH, "DMR")
        self.card = build_card()

    def off(self):
        c = copy.deepcopy(self.cfg); c["wager_policy"] = {k: False for k in c["wager_policy"]}; return c

    def test_each_rule_of_the_decisions_table(self):
        base = score_card(copy.deepcopy(self.card), self.off(), multirace=False)
        res = score_card(copy.deepcopy(self.card), self.cfg, multirace=False)
        for b, r in zip(base["races"], res["races"]):
            self.assertEqual(b["picks"], r["picks"]); self.assertEqual([s["score"] for s in b["sheets"]], [s["score"] for s in r["sheets"]])   # picks and scores untouched
        by = {r["race_no"]: r for r in res["races"]}
        # lone speed (R2, R5): no exotics, doubles and win bets stay
        for rn in (2, 5):
            self.assertTrue(by[rn]["lone_speed"])
            self.assertFalse({w["type"] for w in by[rn]["wagers"]} & {"EXACTA", "TRIFECTA", "SUPERFECTA"})
            self.assertTrue(any("lone-speed" in g["reason"] for g in by[rn]["policy"]["suppressed"]))
        # turf (R3, R6): win bets only; place/show candidates stay
        for rn in (3, 6):
            types = {w["type"] for w in by[rn]["wagers"]}
            self.assertFalse(types & {"EXACTA", "TRIFECTA", "SUPERFECTA"}); self.assertTrue({"PLACE", "SHOW"} <= types)
            self.assertTrue(any(t.startswith("POLICY: no exacta") and "turf" in t for t in by[rn]["other_wagers"]))
        # the suppressed text lines are gone, the structures match the text
        for r in res["races"]:
            labels = {g["label"] for g in r["policy"]["suppressed"]}
            self.assertFalse(labels & set(r["other_wagers"]))
            if any(g["source"] == "primary" for g in r["policy"]["suppressed"]):
                self.assertIn("POLICY:", r["bet_structure"])
        # high-confidence dirt race without lone speed keeps its keys (R1, R4)
        for rn in (1, 4):
            tris = [w for w in by[rn]["wagers"] if w["type"] == "TRIFECTA"]
            self.assertTrue(tris and not any(w["box"] for w in tris))

    def test_medium_and_contentious_drop_the_box(self):
        res = score_card(copy.deepcopy(self.card), self.off(), multirace=False)
        for r in res["races"]:
            if r["confidence"] != "high":
                r["surface"] = "dirt"; r["lone_speed"] = None
        apply_policy(res, self.cfg)
        seen = False
        for r in res["races"]:
            if r["confidence"] != "high":
                seen = True
                self.assertFalse({w["type"] for w in r["wagers"]} & {"TRIFECTA", "SUPERFECTA"}, f"R{r['race_no']}")
                self.assertTrue(any(w["type"] == "EXACTA" for w in r["wagers"]), "the exacta box stays")
                self.assertTrue(any(("exacta box only" in g["reason"]) or ("four-horse trifecta box" in g["reason"]) for g in r["policy"]["suppressed"]))
        self.assertTrue(seen)

    def test_firm_turf_doubles_and_pools_not_offered(self):
        res = score_card(copy.deepcopy(self.card), self.off(), multirace=False)
        by = {r["race_no"]: r for r in res["races"]}
        by[3]["inputs"] = {"track_condition_morning": "Firm", "pools_not_offered": ["Superfecta", "Trifecta"]}
        by[4]["inputs"] = {"track_condition_morning": "Fast", "pools_not_offered": ["Daily Double", "Show"]}
        self.assertEqual(pools_not_offered(by[4]), {"DOUBLE", "SHOW"})
        had_double_into_3 = any(w["type"] == "DOUBLE" and 3 in w["races"] for w in by[2]["wagers"])
        apply_policy(res, self.cfg)
        self.assertFalse(any(w["type"] == "DOUBLE" and 3 in w["races"] for r in res["races"] for w in r["wagers"]))
        if had_double_into_3:
            self.assertTrue(any("firm turf" in g["reason"] for g in by[2]["policy"]["suppressed"]))
        self.assertFalse(any(w["type"] in ("DOUBLE", "SHOW") for w in by[4]["wagers"]))
        self.assertTrue(any("does not offer the show pool" in g["reason"] for g in by[4]["policy"]["suppressed"]))
        self.assertTrue(any(w["type"] == "PLACE" for w in by[4]["wagers"]))

    def test_report_shows_policy_and_place_show(self):
        res = score_card(copy.deepcopy(self.card), self.cfg, multirace=False)
        RS.attach(res, None, self.cfg)
        txt = format_report(res, detail=1)
        self.assertIn("POLICY: no exacta", txt); self.assertIn("PLACE #", txt); self.assertIn("UNTRAINED", txt)


if __name__ == "__main__":
    unittest.main()
