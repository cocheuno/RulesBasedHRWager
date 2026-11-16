"""Phase B: every form's data with provenance.  Provenance / as-of, typed Power Play angles with back-test hit
rates, Equibase inputs and the off-turf switch, weather observations, canonical identity, chart surface, the Desk's
Timeform drop zone and side-by-side ranks.  No score, pick or ticket changes except the surface switch."""
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
os.environ["RACEDESK_WEATHER"] = "off"

from synthetic_card import build_card                                   # noqa: E402
from brisnet_pp.sheet import merge_sheet                                # noqa: E402
from brisnet_pp.chart import surface_from_text, DIST_RE                 # noqa: E402
from handicapper.engine import load_config, score_card, format_report   # noqa: E402
from handicapper.identity import canonical_track, interest_of, norm_name, reconcile   # noqa: E402
from handicapper.pipeline import run_card                               # noqa: E402
from handicapper.provenance import audit_fields, features_as_of, horse_record, missing_flags, card_records   # noqa: E402
from handicapper.results import backtest, format_backtest               # noqa: E402
from handicapper import weather as W                                    # noqa: E402
from timeform_pp.reader import parse_lines                              # noqa: E402

CFG = os.path.join(ROOT, "rules_config.json")


def sheet_for(card):
    """A Power Play sheet (parsed form) for race 1 and 2 of the synthetic card, with angles and ranks."""
    r1 = {h["pgm"]: {"name": h["name"], "ml": h["ml_odds"], "angles": []} for h in card["races"][0]["horses"]}
    r1["1"]["angles"] = ["Exit Key Race", "Drops in class"]
    r1["2"]["angles"] = ["Beaten favorite"]
    r1["3"]["angles"] = ["Debut, hot trainer"]
    races = {1: {"header": "", "wagers": "", "top3": ["1", "2", "6"], "speed": ["1", "6", "2"], "class": ["1", "2", "6"], "pace": ["3", "1", "6"],
                 "top_pick": "1", "horses": r1, "race_no": 1}}
    return {"source": "q.pdf", "track_code": card["track_code"], "date_text": None, "best_bets": [(1, "1")], "races": races}


def timeform_text(card, track_line="DEL MAR 11/06/2026", races=(1,), figs=None, rename=None):
    """A TimeformUS text layer for the synthetic card's races (figures made up; the shape is the real one)."""
    L = [track_line, "Power Picks"]
    for rn in races:
        race = card["races"][rn - 1]
        hs = race["horses"]
        L += ["RACE Sample PACE PROJECTOR", f"{rn} 3Õ 6 F {hs[1]['pgm']} {hs[1]['name']}",
              f"11/06/2026 1:00 PM 80 Claiming Dirt {hs[0]['pgm']} {hs[0]['name']}", f"Wagers: Exacta ($1) {hs[2]['pgm']} {hs[2]['name']}"]
        for i, h in enumerate(hs):
            name = (rename or {}).get(h["pgm"], h["name"])
            fig = (figs or {}).get(h["pgm"], 90 - i)
            L.append(f"{h['pgm']} {name} Colt | Age 4 | Mar | KY-bred Record Top {fig} Fig")
            L.append(f"ML: {h['ml_odds'].replace('/', '-')} | | WT: 122lbs (S) 2026 1 0 0 0 $0 {fig}")
            L.append(f"Running Style: {60 + i} Midpack {70 - i} Owner: O")
            L.append(f"30 Days DMR 80 3Õ Dirt 6 F A B P 1 2 2 2 2 1 {fig} 1 Someone 1 2 Other 1 3 Third 1")
            L.append(f"Oct 07 $20K Claiming Fast 7 122 |L | 3-1 F 1 70 70 70 {fig} clear")
    return "\n".join(L)


class TestProvenance(unittest.TestCase):
    def setUp(self):
        self.card = build_card()

    def test_audit_lists_read_and_unread_fields(self):
        a = audit_fields(self.card)
        for g in ("race", "horse", "pp_line", "work"):
            self.assertTrue(a[g]["read"]); self.assertEqual(a[g]["count"], len(a[g]["read"]) + len(a[g]["unread"]))
        self.assertIn("speed", a["pp_line"]["read"])
        self.assertIn("fractions", a["pp_line"]["unread"])          # a paid-for field no rule reads yet
        self.assertIn("breeder", a["horse"]["unread"])

    def test_as_of_excludes_lines_and_works_dated_after(self):
        r = self.card["races"][0]; h = r["horses"][1]              # ten starts, 25 days apart
        rec = horse_record(h, r, as_of="2026-09-01")
        self.assertEqual(len(rec["lines"]), len([p for p in h["pp"] if p["date"] <= "2026-09-01"]))
        self.assertEqual(rec["excluded_after_as_of"]["lines"], 2)
        self.assertTrue(all(ln["date"] <= "2026-09-01" for ln in rec["lines"]))
        self.assertEqual(rec["raw"]["ml_odds"], {"value": "5/2", "source": "brisnet_pp", "as_of": r["race_date"]})
        self.assertEqual(rec["lines"][0]["source"], "brisnet_pp")
        f_now, f_then = features_as_of(h, r, None), features_as_of(h, r, "2026-09-01")
        self.assertNotEqual(f_now["last_speed"], f_then["last_speed"])
        self.assertEqual(horse_record(h, r)["excluded_after_as_of"], {"lines": 0, "works": 0})

    def test_missingness_flags(self):
        debut = self.card["races"][0]["horses"][2]
        self.assertIn("no_running_lines", missing_flags(debut))
        self.assertNotIn("no_works", missing_flags(debut))
        bare = {"pgm": "9", "pp": [{"date": "2026-01-01", "finish_pos": 3}], "workouts": [], "records": {}}
        self.assertEqual(set(missing_flags(bare)) >= {"no_speed_figures", "no_pace_figures", "no_works", "no_morning_line", "no_trainer_stats", "no_record"}, True)
        recs = card_records(self.card, "2026-10-01")
        self.assertEqual(recs["as_of"], "2026-10-01")
        self.assertEqual(len(recs["races"]), len(self.card["races"]))


class TestPowerPlayTyped(unittest.TestCase):
    def test_every_angle_and_rank_is_kept_with_its_label_and_scored_in_the_backtest(self):
        card = build_card()
        notes = merge_sheet(card, sheet_for(card))
        h1 = card["races"][0]["horses"][0]
        self.assertEqual([a["label"] for a in h1["sheet"]["angles"]], ["Exit Key Race", "Drops in class"])
        self.assertEqual(h1["sheet"]["angles"][0]["key"], "exit_key_race")
        from brisnet_pp.sheet import angle_key
        self.assertEqual((angle_key("ExitKeyRace"), angle_key("HotTnr/JkyCombo"), angle_key("BlueChipTrainerPlay")), ("exit_key_race", "hot_tnr_jky_combo", "blue_chip_trainer_play"))
        self.assertEqual(h1["sheet"]["ranks"], {"top": 1, "speed": 1, "class": 1, "pace": 2})
        self.assertTrue(h1["sheet"]["top_pick"] and h1["sheet"]["best_bet"])
        self.assertEqual(card["races"][0]["horses"][2]["sheet"]["ranks"]["pace"], 1)
        self.assertIsNone(card["races"][0]["horses"][3]["sheet"]["ranks"]["top"])
        cfg = load_config(CFG, track_code="DMR")
        res = score_card(card, cfg, multirace=False)
        s1 = next(s for s in res["races"][0]["sheets"] if s["pgm"] == "1")
        self.assertEqual(s1["sheet"]["ranks"]["speed"], 1)
        self.assertNotIn("sheet", s1["features"])
        # no new points: only the key-race rule (F16) reads the sheet
        plain = score_card(build_card(), cfg, multirace=False)
        for a, b in zip(res["races"][0]["sheets"], plain["races"][0]["sheets"]):
            extra = [h["rule"] for h in a["hits"] if h not in b["hits"]]
            self.assertTrue(set(extra) <= {"F16", "V1"}, extra)          # V1 is the value note (0 points), restated when probabilities move
            self.assertTrue(all(h.get("value") for h in a["hits"] if h["rule"] == "V1"))   # value is beside the score, never in it
            if a["pgm"] != "1":
                self.assertEqual(a["score"], b["score"])
        results = {"track": card["track"], "date": card["date"], "races": [{"race_no": 1, "finish": ["1", "2", "6", "3"], "win": 5.2}]}
        bt = backtest(res, results)
        by = {(a["kind"], a["label"]): a for a in bt["angles"]}
        self.assertEqual((by[("angle", "Exit Key Race")]["fired"], by[("angle", "Exit Key Race")]["won"]), (1, 1))
        self.assertEqual((by[("angle", "Beaten favorite")]["won"], by[("angle", "Beaten favorite")]["itm"]), (0, 1))
        self.assertEqual(by[("rank", "speed #1")]["won"], 1)
        self.assertEqual(by[("rank", "best bet")]["fired"], 1)
        self.assertIn("| angle | Exit Key Race | 1 | 1 | 100.0 | 100.0 |", format_backtest(bt))


class TestEquibaseInputs(unittest.TestCase):
    def changes(self, race_no, notes, pools=("Superfecta",), horses=()):
        return {"track": "Del Mar", "updated": "11/06/2026 10:02 AM", "first_post": "12:30 PM",
                "conditions": {"dirt": "Fast", "turf": "Good"},
                "races": {race_no: {"notes": list(notes), "rail": "Rail at 18 feet", "pools_not_offered": list(pools), "horses": list(horses)}}}

    def test_inputs_are_recorded_and_turf_race_stays_on_turf_without_a_switch(self):
        out = run_card(build_card(), config_path=CFG, multirace=False, changes=self.changes(3, ["Turf race remains on the turf"]))
        r3 = next(r for r in out["result"]["races"] if r["race_no"] == 3)
        self.assertEqual(r3["surface"], "turf")
        self.assertIsNone(r3["surface_switch"])
        self.assertEqual(r3["inputs"]["track_condition_morning"], "Good")
        self.assertEqual(r3["inputs"]["pools_not_offered"], ["Superfecta"])
        self.assertEqual(r3["inputs"]["source"], "equibase_changes")
        r1 = out["result"]["races"][0]
        self.assertEqual(r1["inputs"]["track_condition_morning"], "Fast")
        self.assertEqual(r1["inputs"]["pools_not_offered"], [])
        self.assertIn("equibase_changes", out["result"]["run"]["data_sources"])
        self.assertEqual(out["result"]["run"]["surface_switches"], {})

    def test_off_turf_switches_the_surface_and_activates_mto(self):
        card = build_card()
        r3 = card["races"][2]
        r3["horses"][7]["entry_status"] = "MTO"                     # Dirt Shipper runs only if the race comes off
        base = run_card(copy.deepcopy(card), config_path=CFG, multirace=False)
        b3 = next(r for r in base["result"]["races"] if r["race_no"] == 3)
        self.assertIn("8", b3["alternates"])
        out = run_card(card, config_path=CFG, multirace=False, changes=self.changes(3, ["Off Turf - Race moved to the main track"]))
        o3 = next(r for r in out["result"]["races"] if r["race_no"] == 3)
        self.assertEqual(o3["surface"], "dirt")
        self.assertEqual(o3["surface_switch"], {"from": "turf", "to": "dirt", "source": "equibase_changes"})
        self.assertNotIn("8", o3["alternates"])
        self.assertIsNotNone(next(s for s in o3["sheets"] if s["pgm"] == "8")["rank"])
        self.assertEqual(out["result"]["run"]["surface_switches"], {"3": o3["surface_switch"]})
        self.assertTrue(any("R3: off the turf, scored as dirt; MTO in: #8 Dirt Shipper" in n for n in out["notes"]))
        self.assertIn("Off the turf: scored as dirt", format_report(out["result"], detail=1))
        # the other turf race is untouched
        self.assertEqual(next(r for r in out["result"]["races"] if r["race_no"] == 6)["surface"], "turf")

    def test_off_turf_surface_comes_from_the_track_profile(self):
        card = build_card()
        out = run_card(card, config_path=CFG, multirace=False, track_profile="GP", changes=self.changes(3, ["Off the turf"]))
        self.assertEqual(next(r for r in out["result"]["races"] if r["race_no"] == 3)["surface"], "aw")


class TestWeather(unittest.TestCase):
    def test_manual_text_in_any_order(self):
        o = W.parse_manual("Light Rain / Wind NW at 13 mph Temperature 44°F / Humidity 82%", observed_at_utc="2026-11-06T18:00:00Z")
        self.assertEqual((o["provenance"], o["condition"], o["wind_direction"], o["wind_mph"], o["temperature_f"], o["humidity_pct"]),
                         ("manual", "Light Rain", "NW", 13.0, 44.0, 82))
        o2 = W.parse_manual("Humidity 60%\nTemperature 7C\nWind calm\nOvercast, rain 2 mm")
        self.assertEqual((o2["condition"], o2["temperature_f"], o2["humidity_pct"], o2["precipitation_in"], o2["wind_direction"]), ("Rain", 44.6, 60, 0.08, "CALM"))
        self.assertIsNone(W.parse_manual("nothing useful")["condition"])

    def test_replayed_forecast_gives_one_observation_per_race_and_latest_before_cutoff(self):
        fc = {"daily": [{"date": "2026-11-06", "hourly": [
            {"time": "12:00", "description": "Sunny", "wind_direction": "W", "wind_mph": 8, "temperature_f": 66, "humidity_pct": 50, "precipitation_in": 0.0},
            {"time": "15:00", "description": "Partly cloudy", "wind_direction": "SW", "wind_mph": 12, "temperature_f": 68, "humidity_pct": 55, "precipitation_in": 0.0}]}]}
        posts = {"1": "2026-11-06T20:30:00Z", "2": "2026-11-06T23:00:00Z", "9": "2026-11-07T09:00:00Z"}   # 12:30, 15:00 PT; 01:00 PT next day (no hour)
        obs = W.observations_from_forecast(fc, posts, "America/Los_Angeles", "Del Mar, California", fetched_at_utc="2026-11-06T15:00:00Z")
        self.assertEqual([(o["race_no"], o["condition"]) for o in obs], [(1, "Sunny"), (2, "Partly cloudy")])
        self.assertEqual(obs[0]["forecast_for_utc"], "2026-11-06T20:00:00Z")
        manual = W.parse_manual("Light rain, wind NW 13 mph", observed_at_utc="2026-11-06T20:00:00Z")
        later = W.parse_manual("Heavy rain", observed_at_utc="2026-11-06T22:00:00Z")
        allobs = obs + [manual, later]
        self.assertEqual(W.latest_before(allobs, "2026-11-06T20:28:00Z", 1)["condition"], "Light Rain")   # newest at or before the cutoff
        self.assertEqual(W.latest_before(allobs, "2026-11-06T22:58:00Z", 2)["condition"], "Heavy Rain")
        self.assertEqual(W.latest_before(obs, "2026-11-06T14:00:00Z", 1), None)                           # nothing known yet
        self.assertIn("(manual)", W.summary_text(manual))

    def test_fetch_is_unavailable_without_location_and_never_guesses(self):
        self.assertEqual(W.fetch(None, {"1": "2026-11-06T20:30:00Z"}, "America/Los_Angeles")["status"], "unavailable")
        self.assertEqual(W.fetch("Nowhere", {}, None)["status"], "unavailable")
        import builtins
        real = builtins.__import__

        def no_pw(name, *a, **k):
            if name == "python_weather":
                raise ImportError("not installed")
            return real(name, *a, **k)
        builtins.__import__ = no_pw
        try:
            r = W.fetch("Del Mar, California", {"1": "2026-11-06T20:30:00Z"}, "America/Los_Angeles")
        finally:
            builtins.__import__ = real
        self.assertEqual(r["status"], "unavailable"); self.assertIn("python-weather", r["reason"])

    def test_run_records_supplied_observations_per_race(self):
        card = build_card()
        for r in card["races"]:
            r["post_time"] = "(12:30)/11:30/10:30/ 9:30"
        manual = W.parse_manual("Overcast / Wind SW at 10 mph Temperature 60°F / Humidity 70%", observed_at_utc="2026-11-06T16:00:00Z")
        out = run_card(card, config_path=CFG, multirace=False, weather=[manual])
        self.assertEqual(out["result"]["run"]["weather"]["status"], "supplied")
        self.assertEqual(out["result"]["races"][0]["weather"]["condition"], "Overcast")
        self.assertEqual(out["result"]["races"][0]["weather"]["provenance"], "manual")
        out2 = run_card(build_card(), config_path=CFG, multirace=False)
        self.assertEqual(out2["result"]["run"]["weather"]["status"], "not requested")
        self.assertIsNone(out2["result"]["races"][0]["weather"])


class TestIdentity(unittest.TestCase):
    def test_tracks_names_and_interests(self):
        cfg = load_config(CFG)
        self.assertEqual(canonical_track("BELMONT PARK", cfg), "BEL")
        self.assertEqual(canonical_track("bel", cfg), "BEL")
        self.assertEqual(canonical_track("Belmont at the Big A", cfg), "AQU")
        self.assertIsNone(canonical_track("Nowhere Downs", cfg))
        self.assertEqual(interest_of("1A"), "1")
        self.assertEqual(norm_name("It'sgoodtobequeen (IRE)"), "itsgoodtobequeen")

    def test_reconcile_four_sources(self):
        card = build_card()
        r1 = card["races"][0]
        r1["horses"].append(dict(r1["horses"][0], pgm="1A", name="Dropping Dream Too", entry_status=None))   # coupled with #1
        r1["horses"].append(dict(r1["horses"][1], pgm="8", name="Sucker Punch", entry_status=None))           # duplicate name
        card["races"][2]["surface_switch"] = {"from": "turf", "to": "dirt", "source": "equibase_changes"}; card["races"][2]["surface"] = "dirt"
        tf = parse_lines(timeform_text(card, races=(1, 2), rename={"3": "Fresh Face"}).replace("5 Slow Poke", "9 Slow Poke").splitlines())  # #5 printed as #9: program change
        changes = {"track": "Del Mar", "races": {1: {"notes": [], "rail": None, "pools_not_offered": [],
                   "horses": [{"pgm": "1A", "name": "Dropping Dream Too", "changes": [{"text": "Scratched - Trainer"}]},
                              {"pgm": "6", "name": "Second Timer", "changes": [{"text": "Scratched - Vet"}]},
                              {"pgm": "12", "name": "Phantom", "changes": [{"text": "Scratched - Vet"}]}]}}}
        results = {"track": "Del Mar", "date": card["date"], "races": [{"race_no": 1, "finish": ["2", "1", "3"], "surface": "DIRT"},
                                                                       {"race_no": 4, "finish": ["1", "2"], "surface": "TURF"}]}
        rec = reconcile(card, timeform=tf, changes=changes, results=results, cfg=load_config(CFG))
        x = rec["races"][0]
        self.assertEqual(x["interests"]["1"]["pgms"], ["1", "1A"]); self.assertTrue(x["interests"]["1"]["coupled"])
        self.assertEqual(x["interests"]["1"]["scratched_pgms"], ["1A"]); self.assertFalse(x["interests"]["1"]["scratched"])  # 1 still runs
        self.assertTrue(x["interests"]["6"]["scratched"])
        self.assertEqual(x["program_changes"], [{"source": "timeform", "pgm": "9", "card_pgm": "5", "name": "Slow Poke"}])
        self.assertEqual(x["interests"]["5"]["sources"]["timeform"], ["9"])
        self.assertTrue(any("duplicate horse name 'sucker punch'" in n for n in x["review"]))
        self.assertTrue(any("#12 'Phantom' is not on the card" in n for n in x["review"]))
        self.assertEqual(x["surface"], {"brisnet": "dirt", "timeform": "dirt", "equibase_chart": "dirt"})
        self.assertEqual(rec["missing"]["timeform"], [3, 4, 5, 6, 7, 8][:len(card["races"]) - 2])
        self.assertIn(1, rec["missing"]["results"] and [1] or [1])   # race 1 has a result
        self.assertNotIn(1, rec["missing"]["results"])
        r4 = rec["races"][3]
        self.assertTrue(any("surface differs by source" in n for n in r4["review"]))       # chart says turf, card says dirt, no switch recorded
        r3 = rec["races"][2]
        self.assertEqual(r3["surface"]["equibase_changes"], "dirt")
        self.assertFalse(any("surface differs" in n for n in r3["review"]))
        self.assertEqual(rec["track"]["canonical"], "DMR")


class TestChartSurface(unittest.TestCase):
    def test_surface_words(self):
        self.assertEqual(surface_from_text("(Turf) (1.33)"), "TURF")
        self.assertEqual(surface_from_text("(Inner Turf)"), "TURF")
        self.assertEqual(surface_from_text("(Tapeta) (1.10)"), "SYNTHETIC")
        self.assertIsNone(surface_from_text("(1.09⅖)"))
        m = DIST_RE.match("1 1/16 MILES. (Turf) (1.41⅖) ALLOWANCE OPTIONAL CLAIMING. Purse $100,000")
        self.assertEqual((m.group("dist").strip(), surface_from_text(m.group("parens")), m.group("cls")[:9]), ("1 1/16 MILES", "TURF", "ALLOWANCE"))
        m = DIST_RE.match("6 FURLONGS. (1.08) MAIDEN SPECIAL WEIGHT. Purse $60,000")
        self.assertEqual((m.group("dist").strip(), surface_from_text(m.group("parens")), m.group("cls")[:6]), ("6 FURLONGS", None, "MAIDEN"))

    def test_off_line_decides_when_the_header_does_not(self):
        from brisnet_pp.chart import parse_chart_rows, rows_from_fixture
        data = json.load(open(os.path.join(HERE, "fixtures_chart_rows.json"), encoding="utf-8"))
        rows = rows_from_fixture(data)
        base = parse_chart_rows(rows, 1)
        self.assertEqual((base["surface"], base["surface_source"]), ("DIRT", "off-line"))
        from brisnet_pp.chart import surface_from_off_line
        self.assertEqual(surface_from_off_line("OFF AT 1:41 Start Good For All. Won driving. Course Firm.", "Firm"), "TURF")
        self.assertEqual(surface_from_off_line("OFF AT 1:41 Start Good. Won driving. Track Firm.", "Firm"), "TURF")      # turf-only condition
        self.assertEqual(surface_from_off_line("OFF AT 1:41 Start Good. Won driving. Track Sloppy (sealed).", "Sloppy"), "DIRT")
        self.assertEqual(surface_from_off_line("OFF AT 1:41 Start Good. Won driving. Track Good.", "Good"), "DIRT")


class TestDeskTimeform(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ui.server import Desk
        cls.tmp = tempfile.mkdtemp(prefix="racedesk-b-")
        shutil.copy(CFG, os.path.join(cls.tmp, "rules_config.json"))
        os.makedirs(os.path.join(cls.tmp, "data", "out"))
        cls.card = build_card()
        with open(os.path.join(cls.tmp, "data", "out", "synth.card.json"), "w", encoding="utf-8") as fh:
            json.dump(cls.card, fh)
        cls.desk = Desk(cls.tmp)
        cls.desk.run("synth")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_1_wrong_track_or_day_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            self.desk.save_upload("synth", "timeform", "tf.txt", timeform_text(self.card, "BELMONT PARK 11/06/2026").encode())
        self.assertIn("track", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            self.desk.save_upload("synth", "timeform", "tf.txt", timeform_text(self.card, "DEL MAR 11/07/2026").encode())
        self.assertIn("date", str(cm.exception))
        self.assertFalse(self.desk.files("synth")["timeform"])

    def test_2_timeform_shows_beside_brisnet_and_changes_no_pick(self):
        before = json.load(open(os.path.join(self.tmp, "data", "out", "synth.picks.json"), encoding="utf-8"))
        saved = self.desk.save_upload("synth", "timeform", "tf.txt", timeform_text(self.card, figs={"4": 105}).encode())
        self.assertTrue(saved["saved"].endswith("synth.tfus.txt"))
        d = self.desk.run("synth")
        r1 = d["picks"]["races"][0]
        self.assertEqual(r1["timeform"]["rank"]["4"], 1)                       # Timeform likes #4 ...
        self.assertEqual(r1["timeform"]["power_picks"], ["2", "1", "3"])
        s4 = next(s for s in r1["sheets"] if s["pgm"] == "4")
        self.assertEqual((s4["timeform"]["top_fig"], s4["timeform"]["rank"], s4["timeform"]["style"]), (105, 1, "Midpack"))
        self.assertEqual([s["pgm"] for s in r1["sheets"]], [s["pgm"] for s in before["races"][0]["sheets"]])   # ... the Brisnet order is unchanged
        self.assertEqual([s["score"] for s in r1["sheets"]], [s["score"] for s in before["races"][0]["sheets"]])
        self.assertEqual(r1["picks"], before["races"][0]["picks"])
        self.assertEqual(d["roster"][0]["timeform"]["rank"]["4"], 1)
        self.assertIn("timeformus", d["picks"]["run"]["data_sources"])
        self.assertEqual(d["picks"]["run"]["timeform"]["races"], 1)
        self.assertIsNone(d["picks"]["races"][1]["timeform"])                   # partial file: race 2 has no Timeform block
        md = open(os.path.join(self.tmp, "data", "out", "synth.picks.md"), encoding="utf-8").read()
        self.assertIn("Timeform (TF) rank / Top Fig", md)
        self.assertIn("| 1/105 |", md)
        # the typed weather joins the record as a manual observation and reaches the race
        w = self.desk.save_weather("synth", "Light Rain / Wind NW at 13 mph Temperature 44°F / Humidity 82%")
        self.assertEqual(w["observation"]["temperature_f"], 44.0)
        d = self.desk.run("synth")
        self.assertEqual(d["picks"]["run"]["weather"]["status"], "supplied")
        self.assertEqual(d["picks"]["races"][0]["weather"]["provenance"], "manual")
        # the ledger keeps Timeform and weather as source observations
        from carovex.ledger import connect, import_card
        con = connect(self.tmp)
        n = import_card(self.tmp, "synth", con)
        self.assertGreater(n["observations"], 0)
        provs = {r[0] for r in con.execute("SELECT DISTINCT provider FROM source_observation").fetchall()}
        self.assertIn("timeformus", provs); self.assertIn("weather:manual", provs)


if __name__ == "__main__":
    unittest.main()
