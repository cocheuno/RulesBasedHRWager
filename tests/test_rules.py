"""
Rule-level tests on the synthetic card (tests/synthetic_card.py).

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from synthetic_card import build_card                      # noqa: E402
from handicapper.engine import load_config, score_card, score_race, rules_doc   # noqa: E402
from handicapper import rules as R                         # noqa: E402
from handicapper import multirace as MR                    # noqa: E402


def hits(sheet, rule_id):
    return [h for h in sheet["hits"] if h["rule"] == rule_id]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.card = build_card()
        cls.cfg = load_config(os.path.join(os.path.dirname(HERE), "rules_config.json"))
        cls.result = score_card(cls.card, cls.cfg)
        cls.by_race = {r["race_no"]: r for r in cls.result["races"]}

    def sheet(self, race_no, name):
        return next(s for s in self.by_race[race_no]["sheets"] if s["name"] == name)


class TestInvariants(Base):
    def test_no_rule_errors(self):
        for r in self.result["races"]:
            for s in r["sheets"]:
                for h in s["hits"]:
                    self.assertNotIn("RULE ERROR", h["note"], f"R{r['race_no']} {s['name']}: {h}")

    def test_every_point_traces_to_a_rule(self):
        ids = {rl.id for rl in R.RULES}
        for r in self.result["races"]:
            for s in r["sheets"]:
                self.assertAlmostEqual(s["score"], round(sum(h["points"] for h in s["hits"]), 2), places=1)
                for h in s["hits"]:
                    self.assertIn(h["rule"], ids)
                    self.assertTrue(h["note"])

    def test_deterministic(self):
        again = score_card(build_card(), self.cfg)
        self.assertEqual([r["picks"] for r in again["races"]], [r["picks"] for r in self.result["races"]])
        self.assertEqual(again["multirace"], self.result["multirace"])

    def test_rule_ids_unique_and_documented(self):
        ids = [rl.id for rl in R.RULES] + [rl.id for rl in MR.HRULES]
        self.assertEqual(len(ids), len(set(ids)))
        for rl in R.RULES + MR.HRULES:
            self.assertIn("Basis:", rl.doc, f"{rl.id} has no expert basis in its docstring")
        doc = rules_doc()
        for rl in R.RULES + MR.HRULES:
            self.assertIn(f"| {rl.id} |", doc)


class TestSpeedRules(Base):
    def test_s6_bounce_outweighs_m4_on_career_top(self):
        s = self.sheet(4, "Big Figure Bounce")
        self.assertTrue(hits(s, "S6"))
        self.assertLess(hits(s, "S6")[0]["points"], -6)
        self.assertFalse(hits(s, "M4"), "M4 must not reward the same leap S6 penalises")

    def test_s9_figure_standout(self):
        s = self.sheet(5, "Standout")
        self.assertTrue(hits(s, "S9"))
        self.assertFalse(hits(self.sheet(4, "Big Figure Bounce"), "S9"), "career tops are excluded from S9")

    def test_s8_pairing(self):
        s = self.sheet(4, "Steady Eddie")   # 80, 80, 79 vs par 83
        self.assertTrue(hits(s, "S8"))


class TestSurfaceAwareForm(Base):
    def test_returner_uses_same_surface_figures(self):
        s = self.sheet(3, "Turf Returner")
        f = s["features"]
        self.assertTrue(f["last_off_surface"] and f["use_surface_figs"])
        self.assertEqual(f["speed_last3"], [86, 84], "dirt 70 dropped, turf lines used")
        self.assertEqual(f["last_speed"], 86)
        self.assertTrue(hits(s, "S10"))
        self.assertFalse(hits(s, "F5"), "the 12-length dirt loss is excused")
        self.assertFalse(hits(s, "S5"))

    def test_one_line_or_good_off_surface_race_does_not_switch(self):
        from synthetic_card import build_card
        from handicapper.engine import score_race
        card = build_card()
        r3 = card["races"][2]
        h = next(x for x in r3["horses"] if x["name"] == "Turf Returner")
        h["pp"] = h["pp"][:2]                       # only one turf line left -> no switch
        s = next(x for x in score_race(r3, self.cfg)["sheets"] if x["name"] == "Turf Returner")
        self.assertFalse(s["features"]["use_surface_figs"])
        card = build_card()
        r3 = card["races"][2]
        h = next(x for x in r3["horses"] if x["name"] == "Turf Returner")
        h["pp"][0]["speed"] = 90                    # dirt race was the horse's best figure -> still counts
        s = next(x for x in score_race(r3, self.cfg)["sheets"] if x["name"] == "Turf Returner")
        self.assertFalse(s["features"]["use_surface_figs"])
        self.assertEqual(s["features"]["last_speed"], 90)

    def test_first_timer_on_surface_gets_no_excuse(self):
        s = self.sheet(3, "Dirt Shipper")       # last on dirt, no turf starts: D3 judges it, not S10
        self.assertFalse(s["features"]["use_surface_figs"])
        self.assertFalse(hits(s, "S10"))
        self.assertTrue(hits(s, "D3"))


class TestClassRules(Base):
    def test_c6_claimed_and_dropped(self):
        s = self.sheet(2, "Claimed Then Dropped")
        h = hits(s, "C6")
        self.assertTrue(h)
        self.assertLess(h[0]["points"], 0)

    def test_c7_first_time_for_tag(self):
        s = self.sheet(2, "Tag Virgin")
        self.assertTrue(hits(s, "C7"))
        self.assertFalse(hits(self.sheet(2, "Lone Rocket"), "C7"))

    def test_c8_back_class(self):
        self.assertTrue(hits(self.sheet(4, "Back Classer"), "C8"))

    def test_c9_maiden_graduates(self):
        mcl = hits(self.sheet(3, "Fresh Grad"), "C9")
        self.assertTrue(mcl)
        self.assertLess(mcl[0]["points"], 0)
        # MSW graduate whose winning figure (87) beats par (84) is waived (0 points -> not recorded)
        self.assertFalse(hits(self.sheet(3, "Msw Grad"), "C9"))

    def test_c10_drop_after_win(self):
        h = hits(self.sheet(2, "Drop Off Win"), "C10")
        self.assertTrue(h)
        self.assertLess(h[0]["points"], 0)

    def test_c1_discounts_declining_dropper(self):
        h = hits(self.sheet(2, "Tailing Off"), "C1")
        self.assertFalse(h, "Tailing Off is at the same level; no drop")


class TestPaceFormRules(Base):
    def test_p1_lone_speed(self):
        self.assertTrue(hits(self.sheet(2, "Lone Rocket"), "P1"))
        self.assertEqual(self.by_race[2]["lone_speed"], "1")

    def test_p9_e1_leader_and_duel(self):
        self.assertTrue(hits(self.sheet(2, "Lone Rocket"), "P9"))
        # R6: three E types average E1 97 / 96 / 96 -> all three are in the projected duel
        duel = [hits(self.sheet(6, n), "P9") for n in ("Chalk Speed", "Rival Speed", "Third Speed")]
        self.assertTrue(all(duel))
        self.assertTrue(all(d[0]["points"] < 0 for d in duel))
        self.assertFalse(hits(self.sheet(6, "Ship In"), "P9"))   # E/P a point back is not an E dueller

    def test_p2_hot_pace(self):
        self.assertEqual(self.by_race[3]["pace_shape"], "hot")
        self.assertGreater(hits(self.sheet(3, "Late Thunder"), "P2")[0]["points"], 0)
        self.assertLess(hits(self.sheet(3, "Speedy One"), "P2")[0]["points"], 0)

    def test_f11_trouble_pattern(self):
        self.assertTrue(hits(self.sheet(4, "Trouble Magnet"), "F11"))

    def test_f12_pressured_effort(self):
        self.assertTrue(hits(self.sheet(2, "Lone Rocket"), "F12"))

    def test_f13_beaten_favourite(self):
        h = hits(self.sheet(2, "Beaten Chalk"), "F13")
        self.assertTrue(h)
        self.assertGreater(h[0]["points"], 0)

    def test_f14_freshened(self):
        self.assertTrue(hits(self.sheet(4, "Fresh Legs"), "F14"))

    def test_f15_fast_loser(self):
        self.assertTrue(hits(self.sheet(3, "Fast Loser"), "F15"))


class TestMaidensAndEliminations(Base):
    def test_m2_msw_dropper_wins_r1(self):
        self.assertTrue(hits(self.sheet(1, "Dropping Dream"), "M2"))
        self.assertIn("1", self.by_race[1]["picks"])

    def test_m1_debut_m3_chronic(self):
        self.assertTrue(hits(self.sheet(1, "Fresh Face"), "M1"))
        self.assertTrue(hits(self.sheet(1, "Sucker Punch"), "M3"))

    def test_m4_second_time_starter(self):
        self.assertTrue(hits(self.sheet(1, "Second Timer"), "M4"))

    def test_x_rules(self):
        self.assertTrue(self.sheet(1, "Rusty Gate")["eliminated"])          # X2 long layoff
        self.assertTrue(self.sheet(2, "Out Of Sorts")["eliminated"])        # X1 / X4
        self.assertEqual(self.sheet(1, "Also Ran")["flags"], ["AE - needs a scratch to run"])
        self.assertNotIn("7", self.by_race[1]["picks"])


class TestKeyRaceSheet(unittest.TestCase):
    def test_merge_and_f16(self):
        from synthetic_card import build_card
        from brisnet_pp.sheet import merge_sheet
        from handicapper.engine import load_config, score_card
        card = build_card()
        sheet = {"track_code": "DMR", "date_text": "11/06", "best_bets": [(2, "1")],
                 "races": {2: {"top_pick": "1", "top3": ["1", "3", "5"], "speed": ["1"], "class": ["5"], "pace": ["1"],
                               "horses": {"1": {"name": "Lone Rocket", "angles": ["HotTrainer"]},
                                          "5": {"name": "Tag Virgin", "angles": ["ExitPossibleKeyRace"]},
                                          "3": {"name": "Drop Off Win", "angles": ["ExitKeyRace"]},
                                          "6": {"name": "Wrong Name", "angles": ["ExitKeyRace"]}}}}}
        notes = merge_sheet(card, sheet)
        self.assertTrue(any("#6" in n and "ignored" in n for n in notes), "name mismatch guards the merge")
        self.assertTrue(any("R1: not on the sheet" in n for n in notes))
        res = score_card(card, load_config(None))
        r2 = next(r for r in res["races"] if r["race_no"] == 2)
        self.assertEqual(r2["brisnet"]["top_pick"], "1")
        self.assertEqual(r2["brisnet"]["best_bet"], "1")
        f16 = {s["name"]: [h for h in s["hits"] if h["rule"] == "F16"] for s in r2["sheets"]}
        self.assertEqual(f16["Drop Off Win"][0]["points"], 3.0)
        self.assertEqual(f16["Tag Virgin"][0]["points"], 1.8)
        self.assertFalse(f16["Lone Rocket"])
        self.assertFalse(f16["Tailing Off"])
        # wrong track: nothing merged
        card2 = build_card()
        notes2 = merge_sheet(card2, dict(sheet, track_code="GP"))
        self.assertTrue(notes2 and "not merged" in notes2[0])
        self.assertFalse(any(h.get("sheet_angles") for r in card2["races"] for h in r["horses"]))

    def test_backtest_reports_brisnet_benchmark(self):
        from synthetic_card import build_card
        from brisnet_pp.sheet import merge_sheet
        from handicapper.engine import load_config, score_card
        from handicapper.results import backtest, format_backtest
        card = build_card()
        merge_sheet(card, {"track_code": "DMR", "best_bets": [], "races": {
            2: {"top_pick": "3", "top3": ["3", "1", "5"], "speed": [], "class": [], "pace": [], "horses": {}}}})
        bt = backtest(score_card(card, load_config(None)), {"races": [{"race_no": 2, "finish": ["1", "3"], "win": 8.0}]})
        self.assertEqual(bt["summary"]["brisnet_races"], 1)
        self.assertEqual(bt["summary"]["brisnet_pick_wins"], 0)
        self.assertEqual(bt["summary"]["brisnet_top3"], 1)
        self.assertIn("Brisnet Power Play benchmark", format_backtest(bt))


class TestTrackProfiles(Base):
    CFG_PATH = os.path.join(os.path.dirname(HERE), "rules_config.json")

    def test_profile_layers_over_global(self):
        from handicapper.engine import resolve_track_code
        base = load_config(self.CFG_PATH)
        self.assertEqual(base["track_profile"], "default")
        code = resolve_track_code(self.card, base)
        self.assertEqual(code, "DMR")
        dmr = load_config(self.CFG_PATH, track_code=code)
        self.assertEqual(dmr["track_profile"], "DMR")
        self.assertEqual(dmr["weights"]["P1"], 8)
        self.assertEqual(dmr["multirace"]["pick3"]["base"], 0.5)
        self.assertEqual(dmr["multirace"]["logit_scale"], base["multirace"]["logit_scale"], "untouched keys survive the layer")
        unknown = load_config(self.CFG_PATH, track_code="ZZZ")
        self.assertTrue(unknown["track_profile"].startswith("default"))
        self.assertEqual(unknown["weights"], base["weights"])

    def test_alias_fallback_and_report_header(self):
        from handicapper.engine import resolve_track_code, format_report
        base = load_config(self.CFG_PATH)
        card = {"track": "Santa Anita", "track_code": None}
        self.assertEqual(resolve_track_code(card, base), "SA")
        self.assertIsNone(resolve_track_code({"track": "Nowhere Downs"}, base))
        res = score_card(self.card, load_config(self.CFG_PATH, track_code="DMR"))
        self.assertEqual(res["track_profile"], "DMR")
        self.assertIn("track profile: DMR", format_report(res, detail=0))
        # the profile changes points, not structure: P1 for the R2 lone speed is 8 under DMR, 7 by default
        r2 = next(r for r in res["races"] if r["race_no"] == 2)
        p1 = next(h for s in r2["sheets"] for h in s["hits"] if h["rule"] == "P1")
        self.assertEqual(p1["points"], 8.0)


class TestWeights(Base):
    def test_prime_power_and_comment_weights_are_moderate(self):
        w = {rl.id: rl.weight for rl in R.RULES}
        self.assertLessEqual(w["S7"], w["S1"])
        self.assertLess(w["Q1"], 1.0)
        self.assertLess(w["Q2"], 1.0)

    def test_config_override_changes_score(self):
        cfg = load_config(None)
        cfg["weights"]["S1"] = 0
        cfg["disabled"] = ["S7"]
        r = score_race(self.card["races"][5], cfg)
        for s in r["sheets"]:
            self.assertFalse(hits(s, "S1"))
            self.assertFalse(hits(s, "S7"))


if __name__ == "__main__":
    unittest.main()
