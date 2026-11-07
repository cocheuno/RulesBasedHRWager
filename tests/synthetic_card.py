"""
Synthetic, hand-written card in the exact shape produced by brisnet_pp.parser.

No real Brisnet / Equibase data is reproduced here: every horse, figure and
comment is invented so the fixture can live in the repository.  Values are
explicit (no random generation) so test expectations are stable.

    python tests/synthetic_card.py out.json     # write the card for pick.py / validate_parse.py
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta

TODAY = date(2026, 11, 6)
TRACK = "Del Mar"
TRK = "DMR"


def _iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def _call(pos, lengths=0.0):
    return {"pos": pos, "lengths": lengths, "margin": None, "raw": str(pos) if pos else "-"}


def pp(days_ago, cls, price, speed, e1, e2, lp, finish, beaten, comment, *, surface="dirt", furlongs=8.0,
       cr=None, rr=None, c1=1, c2=2, odds=4.0, favorite=False, claimed=False, field=8, lead_margin=None, track=TRK,
       jockey="RiderA", race_type=None):
    """One past-performance line.  cls is the class code; race_type the Brisnet text."""
    rt = race_type or {"MCL": f"MC{price}", "MSW": f"Mdn{price // 1000}k", "MOC": f"Moc{price}",
                       "CLM": f"Clm{price}", "OC": f"OC{price}n1x", "ALW": f"Alw{price // 1000}k",
                       "STK": "StkB100k", "HCP": "Hcp", "STR": "Str50000"}[cls]
    if claimed:
        rt += "-c"
    won = finish == 1
    calls = {"start": _call(c1), "call1": _call(c1, 0.5 if c1 > 1 else 0.0), "call2": _call(c2, 1.0 if c2 > 1 else 0.0),
             "stretch": _call(max(1, finish - (1 if comment.startswith("rallied") else 0)), beaten if finish > 1 else 0.0),
             "finish": _call(finish, beaten if finish > 1 else 0.0)}
    tf = [{"name": "WnrAbbr", "margin_lengths": lead_margin if lead_margin is not None else 1.0, "margin": None},
          {"name": "PlcAbbr", "margin_lengths": 0.5, "margin": None}, {"name": "ShwAbbr", "margin_lengths": 1.0, "margin": None}]
    return {
        "raw": "synthetic", "date": _iso(days_ago), "track": track, "race_no": 5, "foreign": False,
        "surface": surface, "about_or_alt_course": False, "distance_furlongs": furlongs,
        "distance_text": f"{furlongs:g}f", "track_condition": "fm" if surface == "turf" else "ft",
        "fractions": [22.4, 45.8], "final_time": 110.2, "age_restriction": "3up",
        "race_rating": rr if rr is not None else 100, "race_type_raw": rt, "fillies_mares": False, "state_bred": False,
        "race_type": rt, "class_code": cls, "claimed": claimed, "race_purse_or_price": price,
        "class_rating": cr if cr is not None else 100, "e1": e1, "e2": e2, "lp": lp, "c1": None, "c2": None,
        "speed": speed, "post": 4, **calls, "jockey": jockey, "weight": 122, "apprentice": 0,
        "lasix": True, "blinkers": False, "front_wraps": False, "med_equip_raw": "L", "favorite": favorite,
        "odds": odds, "coupled_entry": False, "field_size": field, "top_finishers_raw": "", "top_finishers": tf,
        "comment": comment, "finish_pos": finish, "beaten_lengths": 0.0 if won else beaten, "won": won,
        "dnf": False, "is_route": furlongs >= 8.0,
    }


def work(days_ago, furlongs, rank, of, bullet=False):
    d = TODAY - timedelta(days=days_ago)
    return {"date": d.strftime("%d%b'%y").replace("May", "May"), "track": TRK, "turf": False,
            "distance_furlongs": float(furlongs), "condition": "ft", "time": 48.0 + furlongs, "type": "H",
            "rank": rank, "of": of, "bullet": bullet or rank == 1}


def stat(cat, starts, win, itm, roi, flag=False):
    return {"category": cat, "flag": flag, "starts": starts, "win_pct": win, "itm_pct": itm, "roi": roi}


def rec(starts, w, p, s, best=None):
    return {"starts": starts, "win": w, "place": p, "show": s, "earnings": None, "best_speed": best}


def horse(pgm, name, ml, style, pts, pps, *, works=None, trainer_pct=12, trainer_starts=120, jockey_pct=14,
          jockey_starts=400, prime_power=100.0, age=4, sex="g", weight=122, positives=(), negatives=(), angles=(),
          records=None, ped=None, entry_status=None, blinkers=None, first_lasix=False, jt_combo=None, ped_stats=None,
          jockey="Rider A", trainer="Trainer A", post=None, days_override=None, trainer_meet=None):
    n, d = ml.split("/")
    pps = list(pps)
    starts = len(pps)
    wins = sum(1 for p in pps if p["won"])
    places = sum(1 for p in pps if p["finish_pos"] == 2)
    shows = sum(1 for p in pps if p["finish_pos"] == 3)
    recs = {"life": rec(starts, wins, places, shows, max((p["speed"] for p in pps), default=None))}
    dirt = [p for p in pps if p["surface"] == "dirt"]
    turf = [p for p in pps if p["surface"] == "turf"]
    for key, lst in (("fst", dirt), ("trf", turf)):
        recs[key] = rec(len(lst), sum(p["won"] for p in lst), sum(p["finish_pos"] == 2 for p in lst),
                        sum(p["finish_pos"] == 3 for p in lst), max((p["speed"] for p in lst), default=None))
    recs["dis"] = rec(0, 0, 0, 0)
    recs["track"] = rec(0, 0, 0, 0)
    recs["track_code"] = TRK
    if records:
        recs.update(records)
    days = days_override if days_override is not None else (
        (TODAY - date.fromisoformat(pps[0]["date"])).days if pps else None)
    tstats = [stat(str(TODAY.year), trainer_starts, trainer_pct, trainer_pct * 2 + 10, 0.0, flag=trainer_pct >= 20)] + list(angles)
    jstats = [stat(str(TODAY.year), jockey_starts, jockey_pct, jockey_pct * 2 + 12, -0.1)]
    if jt_combo:
        jstats.append(stat("JKYw/ Trn L60", *jt_combo))
    return {
        "pgm": str(pgm), "post": post or int(pgm), "entry_status": entry_status, "apprentice_allowance": 0,
        "ml_odds": ml, "ml_decimal": round(int(n) / int(d), 3), "name": name, "run_style": style, "speed_pts": pts,
        "name_flag": None, "claim_price": None, "color": "b", "sex": sex, "age": age, "foal_month": 3, "sale": None,
        "prime_power": prime_power, "prime_power_rank": None, "owner": "Owner", "silks": "silks",
        "sire": "Sire", "sire_sire": "SireSire", "stud_fee": None, "dam": "Dam", "dam_sire": "DamSire",
        "breeder": "Breeder", "bred_state": "KY", "trainer": trainer,
        "trainer_meet": trainer_meet or {"starts": 10, "win": 2, "place": 2, "show": 1, "win_pct": 20},
        "jockey": jockey, "jockey_meet": {"starts": 50, "win": 8, "place": 7, "show": 6, "win_pct": 16},
        "weight": weight, "lasix": True, "first_lasix": first_lasix, "blinkers_change": blinkers,
        "records": recs, "pedigree_ratings": ped or {"fst": "105", "off": "100", "dis": "104", "trf": "98"},
        "jockey_stats": jstats, "trainer_stats": tstats,
        "pedigree_stats": ped_stats or {"sire": {"awd": 6.8, "first_pct": 12, "mud_pct": 15, "spi": 1.5},
                                        "dam_sire": {"awd": 7.0}, "dam": {"dpi": 1.2}},
        "positives": list(positives), "negatives": list(negatives), "pp": pps, "workouts": list(works or []),
        "days_since_last": days, "summary": None, "lifetime_starts": starts, "first_time_starter": starts == 0,
    }


def race(no, class_text, class_code, price, dist_f, surface, pars, horses, bias=None, header=None):
    pps = sorted(horses, key=lambda h: -(h["prime_power"] or 0))
    for i, h in enumerate(pps, 1):
        h["prime_power_rank"] = i
    return {
        "race_no": no, "header_text": header or f"{class_text} {dist_f:g} Furlongs 3&up Friday, November 06, 2026",
        "class_text": class_text, "class_code": class_code, "claiming_price": price,
        "distance_text": f"{dist_f:g} Furlongs" if dist_f < 8 else "1 Mile", "distance_furlongs": dist_f,
        "surface": surface, "is_route": dist_f >= 8.0, "purse": 40000, "conditions": "", "age_text": "3&up",
        "sex_text": None, "fillies_mares": False, "state_bred": False, "race_date": TODAY.isoformat(),
        "pars": pars, "top3": {"speed_last_race": [], "prime_power": [], "class_rating": [], "best_speed_at_dist": []},
        "wagers": "", "post_time": None, "racetype_stats": None, "rankings": None, "summary": None,
        "bias": bias or {"meet": {"races": 40, "runstyle": {"E": {"impact": 1.35, "win_pct": 30}, "E/P": {"impact": 1.1, "win_pct": 25},
                                                           "P": {"impact": 0.8, "win_pct": 15}, "S": {"impact": 0.55, "win_pct": 8}},
                                  "post": {"RAIL": {"impact": 1.0}, "1-3": {"impact": 1.0}, "4-7": {"impact": 1.0}, "8+": {"impact": 0.65}}},
                         "week": {"races": 3, "runstyle": {}, "post": {}}},
        "horses": horses, "field_size": len(horses), "pages": [],
    }


# ---------------------------------------------------------------------------
# Races.  Each is designed to exercise particular rules (named in the comments).
# ---------------------------------------------------------------------------
def build_card() -> dict:
    races = []

    # R1: $16k maiden claimer, 1 mile dirt.  MSW dropper (M2), chronic maiden (M3), debut runner (M1),
    #     long-layoff elimination (X2), hopelessly slow (X1), also-eligible (X3).
    r1 = [
        horse(1, "Dropping Dream", "8/5", "E/P", 6, [
            pp(30, "MSW", 70000, 74, 88, 84, 70, 5, 6.5, "4w turn, weakened", c1=2, c2=2, odds=9.0, cr=104),
            pp(65, "MSW", 70000, 71, 86, 83, 68, 6, 8.0, "chased, tired", c1=3, c2=3, odds=12.0, cr=103),
        ], works=[work(7, 5, 3, 30), work(14, 4, 10, 40)], trainer_pct=18, prime_power=118.0, age=3,
            positives=["Drops in class today", "Highest last race speed rating"], angles=[stat("Maiden Claiming", 40, 21, 50, 0.4, True)]),
        horse(2, "Sucker Punch", "5/2", "P", 3, [
            pp(20 + 25 * i, "MCL", 16000, 70 - i, 82, 80, 72, 2, 1.0 + i * 0.5, "rallied, missed", c1=5, c2=4, odds=2.5, favorite=(i == 0), cr=96)
            for i in range(10)
        ], works=[work(10, 4, 8, 30)], prime_power=112.0, negatives=["Failed as favorite in last race"]),
        horse(3, "Fresh Face", "4/1", "E", 7, [], works=[work(6, 5, 1, 25, True), work(13, 5, 2, 20), work(20, 4, 5, 30), work(27, 4, 3, 22)],
              trainer_pct=22, prime_power=105.0, age=3, angles=[stat("1st time starter", 60, 18, 40, 0.3, True)],
              ped_stats={"sire": {"awd": 6.5, "first_pct": 16, "mud_pct": 12, "spi": 2.1}, "dam_sire": {"awd": 7.2}, "dam": {"dpi": 1.0}}),
        horse(4, "Rusty Gate", "20/1", "S", 0, [
            pp(400, "MCL", 20000, 60, 78, 74, 66, 7, 14.0, "no factor", c1=8, c2=8, odds=30.0, cr=92),
            pp(430, "MCL", 20000, 58, 77, 73, 65, 8, 16.0, "outrun", c1=8, c2=8, odds=40.0, cr=92),
        ], works=[work(8, 4, 20, 40)], trainer_pct=5, trainer_starts=80, prime_power=90.0),
        horse(5, "Slow Poke", "15/1", "P", 2, [
            pp(25, "MCL", 16000, 62, 80, 77, 70, 6, 11.0, "no rally", c1=6, c2=6, odds=20.0, cr=93),
            pp(50, "MCL", 16000, 64, 81, 78, 69, 5, 9.0, "empty", c1=6, c2=5, odds=18.0, cr=93),
            pp(80, "MCL", 16000, 61, 79, 76, 68, 7, 12.0, "faded", c1=5, c2=6, odds=25.0, cr=93),
        ], works=[work(9, 4, 15, 35)], prime_power=95.0),
        horse(6, "Second Timer", "6/1", "E/P", 5, [
            pp(35, "MCL", 25000, 72, 86, 84, 71, 3, 2.5, "bumped start, rallied", c1=3, c2=3, odds=6.0, cr=98),
        ], works=[work(12, 5, 2, 24), work(19, 4, 6, 30)], trainer_pct=15, prime_power=110.0, age=3),
        horse(7, "Also Ran", "10/1", "P", 3, [
            pp(40, "MCL", 16000, 68, 82, 80, 72, 4, 4.0, "mild bid", c1=5, c2=4, odds=8.0, cr=95),
            pp(70, "MCL", 16000, 66, 80, 79, 71, 5, 5.5, "no late bid", c1=5, c2=5, odds=10.0, cr=95),
        ], works=[work(11, 4, 12, 30)], prime_power=100.0, entry_status="AE"),
    ]
    races.append(race(1, "MC 16000", "MCL", 16000, 8.0, "dirt", {"e1": 81, "e2": 77, "late": 78, "speed": 77}, r1))

    # R2: $12.5k claiming sprint, 6f dirt.  Lone speed (P1/P9), class drop for a reason (C1), drop after a win (C10),
    #     claimed-and-dropped (C6), beaten favourite with excuse (F13), bad effort (F5), first time for a tag (C7).
    r2 = [
        horse(1, "Lone Rocket", "3/1", "E", 8, [
            pp(28, "CLM", 12500, 80, 96, 95, 74, 2, 0.5, "set pace, dueled, just missed", c1=1, c2=1, odds=3.5, cr=100),
            pp(56, "CLM", 12500, 78, 95, 94, 73, 3, 2.0, "pace, weakened late", c1=1, c2=1, odds=4.0, cr=100),
            pp(84, "CLM", 16000, 79, 97, 95, 72, 4, 3.5, "dueled, tired", c1=1, c2=1, odds=6.0, cr=102),
        ], works=[work(10, 4, 4, 30)], trainer_pct=14, prime_power=120.0, jt_combo=(8, 25, 50, 0.6)),
        horse(2, "Beaten Chalk", "5/2", "E/P", 5, [
            pp(21, "CLM", 12500, 76, 90, 90, 78, 4, 3.0, "steadied 3/8, 5w, willing", c1=4, c2=4, odds=1.8, favorite=True, cr=100),
            pp(49, "CLM", 12500, 82, 92, 92, 80, 1, 0.0, "drew off", c1=2, c2=1, odds=2.5, cr=100, lead_margin=3.5),
            pp(77, "CLM", 10000, 79, 91, 91, 79, 2, 1.0, "gamely", c1=3, c2=2, odds=4.0, cr=98),
        ], works=[work(9, 4, 2, 30)], trainer_pct=19, jockey_pct=19, prime_power=121.5,
            negatives=["Failed as favorite in last race"], angles=[stat("Btn favorite", 30, 23, 55, 0.2, True)]),
        horse(3, "Drop Off Win", "7/2", "P", 3, [
            pp(24, "CLM", 25000, 81, 90, 89, 83, 1, 0.0, "rallied, driving", c1=5, c2=4, odds=5.0, cr=104, lead_margin=1.0),
            pp(52, "CLM", 25000, 76, 89, 88, 80, 5, 5.0, "no late kick", c1=6, c2=5, odds=7.0, cr=104),
            pp(90, "CLM", 32000, 77, 90, 88, 79, 6, 7.0, "evenly", c1=6, c2=6, odds=12.0, cr=106),
        ], works=[work(8, 4, 9, 30)], trainer_pct=9, trainer_starts=150, prime_power=119.0),
        horse(4, "Claimed Then Dropped", "6/1", "E/P", 4, [
            pp(30, "CLM", 20000, 74, 91, 89, 76, 6, 8.5, "faded", c1=2, c2=3, odds=6.0, cr=102, claimed=True),
            pp(60, "CLM", 20000, 79, 92, 91, 78, 2, 1.5, "gamely", c1=2, c2=2, odds=5.0, cr=102),
            pp(95, "CLM", 16000, 78, 91, 90, 77, 1, 0.0, "handily", c1=1, c2=1, odds=3.0, cr=100, lead_margin=2.5),
        ], works=[work(7, 4, 5, 30)], trainer_pct=11, prime_power=115.0),
        horse(5, "Tag Virgin", "4/1", "P", 2, [
            pp(33, "OC", 50000, 77, 88, 87, 82, 5, 4.5, "mild rally", c1=6, c2=6, odds=15.0, cr=108),
            pp(70, "ALW", 60000, 76, 87, 86, 81, 6, 6.0, "no threat", c1=7, c2=6, odds=20.0, cr=110),
            pp(110, "MSW", 70000, 75, 86, 86, 80, 1, 0.0, "driving", c1=5, c2=3, odds=4.0, cr=104, lead_margin=1.5),
        ], works=[work(12, 5, 6, 30)], trainer_pct=16, prime_power=117.0),
        horse(6, "Tailing Off", "12/1", "S", 0, [
            pp(18, "CLM", 12500, 62, 80, 82, 70, 8, 16.0, "no factor", c1=8, c2=8, odds=15.0, cr=96),
            pp(40, "CLM", 12500, 70, 84, 85, 75, 6, 9.0, "faded", c1=7, c2=7, odds=10.0, cr=96),
            pp(66, "CLM", 12500, 75, 86, 86, 78, 3, 3.0, "rallied", c1=8, c2=7, odds=8.0, cr=96),
        ], works=[], trainer_pct=6, trainer_starts=90, prime_power=98.0, negatives=["Poor Speed Figures"]),
        horse(7, "Out Of Sorts", "30/1", "P", 1, [
            pp(45, "CLM", 8000, 58, 78, 77, 68, 7, 15.0, "trailed", c1=7, c2=7, odds=40.0, cr=88),
            pp(80, "CLM", 8000, 60, 79, 78, 69, 6, 12.0, "outrun", c1=7, c2=7, odds=35.0, cr=88),
            pp(120, "CLM", 8000, 57, 77, 77, 66, 8, 18.0, "no factor", c1=8, c2=8, odds=50.0, cr=88),
        ], works=[work(15, 3, 30, 40)], trainer_pct=8, prime_power=85.0),
    ]
    races.append(race(2, "Clm 12500", "CLM", 12500, 6.0, "dirt", {"e1": 92, "e2": 94, "late": 80, "speed": 80}, r2))

    # R3: OC 20k n1x, 1 mile turf.  Hot pace (P2), closers with late pace (P4/P8), maiden winners moving up (C9),
    #     pressured-pace effort (F12), hidden form (F15), paired figures (S8), figure standout (S9), surface switch (D3).
    r3 = [
        horse(1, "Speedy One", "4/1", "E", 8, [
            pp(30, "OC", 20000, 86, 92, 90, 78, 3, 2.0, "pressed pace, dueled, weakened", surface="turf", c1=1, c2=1, odds=5.0, cr=108),
            pp(60, "OC", 20000, 84, 91, 90, 77, 4, 3.5, "dueled, tired", surface="turf", c1=1, c2=1, odds=6.0, cr=108),
        ], works=[work(10, 4, 5, 30)], prime_power=122.0),
        horse(2, "Speedy Two", "6/1", "E", 7, [
            pp(25, "OC", 20000, 83, 93, 91, 76, 5, 4.0, "vied for lead, gave way", surface="turf", c1=2, c2=1, odds=8.0, cr=108),
            pp(55, "ALW", 60000, 82, 92, 90, 75, 6, 5.0, "pace, faltered", surface="turf", c1=1, c2=2, odds=10.0, cr=110),
        ], works=[work(9, 4, 7, 30)], prime_power=118.0),
        horse(3, "Speedy Three", "8/1", "E", 7, [
            pp(35, "OC", 20000, 81, 94, 92, 74, 7, 6.0, "set pace, stopped", surface="turf", c1=1, c2=1, odds=12.0, cr=108),
            pp(70, "OC", 20000, 80, 93, 91, 73, 6, 5.5, "dueled, faded", surface="turf", c1=1, c2=1, odds=9.0, cr=108),
        ], works=[work(11, 4, 8, 30)], prime_power=114.0),
        horse(4, "Late Thunder", "5/2", "S", 0, [
            pp(28, "OC", 20000, 87, 80, 84, 92, 2, 0.5, "rallied widest, just missed", surface="turf", c1=8, c2=7, odds=3.0, cr=108),
            pp(56, "OC", 20000, 86, 81, 84, 91, 2, 1.0, "closed well", surface="turf", c1=8, c2=8, odds=4.0, cr=108),
            pp(84, "OC", 20000, 85, 80, 83, 90, 3, 1.5, "rallied", surface="turf", c1=8, c2=7, odds=5.0, cr=108),
        ], works=[work(8, 4, 3, 30)], trainer_pct=20, jockey_pct=20, prime_power=125.0,
            positives=["Highest last race speed rating", "Best Turf speed is faster than the Avg Winning Speed"]),
        horse(5, "Fast Loser", "7/2", "P", 3, [
            pp(32, "ALW", 60000, 89, 86, 88, 88, 4, 4.5, "4w, evenly", surface="turf", c1=5, c2=5, odds=6.0, cr=112),
            pp(64, "OC", 20000, 84, 85, 87, 86, 1, 0.0, "driving", surface="turf", c1=4, c2=3, odds=3.0, cr=108, lead_margin=1.0),
        ], works=[work(12, 5, 2, 25)], trainer_pct=17, prime_power=121.0),
        horse(6, "Fresh Grad", "6/1", "P", 3, [
            pp(26, "MCL", 32000, 78, 85, 86, 82, 1, 0.0, "handily", surface="turf", c1=4, c2=3, odds=2.0, favorite=True, cr=100, lead_margin=2.0),
            pp(60, "MCL", 32000, 74, 84, 85, 80, 2, 1.0, "gamely", surface="turf", c1=5, c2=4, odds=4.0, cr=100),
        ], works=[work(10, 4, 4, 30)], prime_power=108.0, age=3, negatives=["Moves up in class from last start"]),
        horse(7, "Msw Grad", "9/2", "E/P", 5, [
            pp(29, "MSW", 70000, 87, 90, 89, 84, 1, 0.0, "drew off", surface="turf", c1=2, c2=2, odds=3.0, cr=106, lead_margin=4.0),
            pp(62, "MSW", 70000, 80, 88, 88, 82, 3, 2.5, "bid, hung", surface="turf", c1=3, c2=3, odds=5.0, cr=106),
        ], works=[work(9, 5, 3, 30)], trainer_pct=24, prime_power=116.0, age=3),
        horse(8, "Dirt Shipper", "10/1", "E/P", 5, [
            pp(40, "OC", 20000, 85, 92, 90, 80, 2, 1.0, "gamely", c1=2, c2=2, odds=5.0, cr=108),
            pp(75, "OC", 20000, 84, 91, 90, 79, 3, 2.0, "willing", c1=2, c2=2, odds=6.0, cr=108),
        ], works=[work(10, 5, 10, 30)], prime_power=112.0, ped={"fst": "110", "off": "100", "dis": "104", "trf": "92"},
            angles=[stat("Dirt to Turf", 20, 5, 20, -0.5)]),
        horse(9, "Turf Returner", "8/1", "P", 3, [
            pp(30, "OC", 20000, 70, 84, 84, 74, 7, 12.0, "no factor", c1=6, c2=7, odds=9.0, cr=108),                    # dirt flop
            pp(65, "OC", 20000, 86, 86, 87, 86, 3, 2.0, "rallied", surface="turf", c1=5, c2=5, odds=6.0, cr=108),
            pp(100, "OC", 20000, 84, 85, 86, 85, 2, 1.0, "gamely", surface="turf", c1=6, c2=5, odds=7.0, cr=108),
        ], works=[work(9, 4, 6, 30)], trainer_pct=13, prime_power=113.0, post=9,
            positives=["May improve while returning to Turf"]),
    ]
    races.append(race(3, "OC 20000n1x", "OC", 20000, 8.0, "turf", {"e1": 84, "e2": 84, "late": 82, "speed": 84}, r3,
                      header="OC 20000n1x 1 Mile (T) 3&up Friday, November 06, 2026",
                      bias={"meet": {"races": 30, "runstyle": {"E": {"impact": 0.7}, "E/P": {"impact": 1.0}, "P": {"impact": 1.15}, "S": {"impact": 1.4}},
                                     "post": {"RAIL": {"impact": 1.0}, "1-3": {"impact": 1.0}, "4-7": {"impact": 1.0}, "8+": {"impact": 0.9}}},
                            "week": {"races": 2, "runstyle": {}, "post": {}}}))

    # R4: Clm 10000 route dirt, contentious field (spread leg for multi-race), back class (C8), freshened (F14),
    #     trouble pattern (F11), second-off-layoff (F7), rider upgrade (K6).
    r4 = [
        horse(1, "Back Classer", "5/1", "P", 3, [
            pp(45, "CLM", 10000, 76, 84, 83, 80, 5, 6.0, "no rally", c1=5, c2=5, odds=8.0, cr=98),
            pp(75, "CLM", 12500, 77, 85, 84, 80, 6, 7.0, "evenly", c1=6, c2=6, odds=9.0, cr=99),
            pp(110, "CLM", 16000, 78, 85, 84, 81, 4, 4.0, "mild bid", c1=5, c2=5, odds=10.0, cr=100),
            pp(150, "OC", 40000, 84, 87, 86, 84, 2, 1.0, "gamely", c1=4, c2=3, odds=6.0, cr=108),
            pp(190, "OC", 40000, 85, 88, 87, 85, 1, 0.0, "driving", c1=3, c2=2, odds=4.0, cr=108, lead_margin=1.0),
        ], works=[work(8, 5, 4, 30), work(20, 4, 6, 30)], trainer_pct=16, prime_power=114.0),
        horse(2, "Fresh Legs", "4/1", "E/P", 5, [
            pp(40, "CLM", 10000, 74, 86, 85, 78, 6, 7.0, "weakened", c1=2, c2=2, odds=5.0, cr=98),
            pp(58, "CLM", 10000, 78, 87, 86, 79, 4, 3.5, "tired", c1=2, c2=2, odds=4.0, cr=98),
            pp(76, "CLM", 10000, 81, 88, 87, 80, 2, 1.0, "gamely", c1=1, c2=1, odds=3.0, cr=98),
            pp(94, "CLM", 10000, 82, 88, 87, 81, 1, 0.0, "driving", c1=1, c2=1, odds=3.0, cr=98, lead_margin=1.0),
        ], works=[work(6, 5, 3, 30), work(16, 4, 5, 30), work(26, 4, 9, 30)], trainer_pct=13, prime_power=113.0),
        horse(3, "Trouble Magnet", "9/2", "P", 4, [
            pp(30, "CLM", 10000, 80, 85, 84, 82, 3, 2.0, "checked 1/4, 5w, rallied", c1=6, c2=5, odds=4.0, cr=98),
            pp(60, "CLM", 10000, 79, 85, 84, 81, 4, 3.0, "blocked str, late", c1=6, c2=6, odds=5.0, cr=98),
            pp(90, "CLM", 10000, 81, 86, 85, 82, 2, 1.0, "closed", c1=6, c2=5, odds=6.0, cr=98),
        ], works=[work(9, 4, 5, 30)], trainer_pct=12, prime_power=115.0),
        horse(4, "Comebacker", "7/2", "E/P", 6, [
            pp(35, "CLM", 10000, 79, 88, 87, 79, 3, 2.5, "pressed, willing", c1=2, c2=2, odds=5.0, cr=98),
            pp(140, "CLM", 12500, 82, 89, 88, 80, 1, 0.0, "handily", c1=1, c2=1, odds=3.0, cr=99, lead_margin=2.0),
            pp(170, "CLM", 12500, 80, 88, 87, 79, 2, 0.5, "gamely", c1=2, c2=1, odds=4.0, cr=99),
        ], works=[work(10, 5, 2, 30)], trainer_pct=15, jockey_pct=19, prime_power=116.0, jockey="Rider B",
            angles=[stat("2nd off layoff", 30, 20, 45, 0.3, True)], positives=["Eligible to improve in 2nd start since layoff"]),
        horse(5, "Steady Eddie", "3/1", "P", 3, [
            pp(28, "CLM", 10000, 80, 86, 85, 81, 2, 0.5, "gamely", c1=5, c2=4, odds=3.0, cr=98),
            pp(56, "CLM", 10000, 80, 86, 85, 81, 3, 1.5, "willing", c1=5, c2=4, odds=3.5, cr=98),
            pp(84, "CLM", 10000, 79, 85, 84, 80, 2, 1.0, "rallied", c1=5, c2=5, odds=4.0, cr=98),
            pp(112, "CLM", 10000, 78, 85, 84, 80, 3, 2.0, "closed", c1=5, c2=5, odds=4.0, cr=98),
        ], works=[work(7, 4, 6, 30)], trainer_pct=14, jockey_pct=18, prime_power=117.0,
            positives=["Ran 2nd vs similar in last race"]),
        horse(6, "Big Figure Bounce", "6/1", "E", 7, [
            pp(14, "CLM", 10000, 90, 92, 91, 82, 1, 0.0, "drew off", c1=1, c2=1, odds=6.0, cr=98, lead_margin=5.0),
            pp(42, "CLM", 10000, 76, 88, 87, 76, 5, 5.0, "weakened", c1=1, c2=2, odds=8.0, cr=98),
            pp(70, "CLM", 10000, 77, 88, 87, 77, 4, 4.0, "tired", c1=1, c2=1, odds=7.0, cr=98),
        ], works=[], trainer_pct=10, prime_power=118.0),
        horse(7, "Outside Chance", "15/1", "S", 1, [
            pp(32, "CLM", 10000, 72, 80, 81, 79, 7, 9.0, "no factor", c1=8, c2=8, odds=20.0, cr=98),
            pp(64, "CLM", 10000, 74, 81, 82, 80, 6, 8.0, "outrun", c1=8, c2=8, odds=18.0, cr=98),
            pp(96, "CLM", 10000, 73, 80, 81, 79, 8, 10.0, "trailed", c1=8, c2=8, odds=25.0, cr=98),
        ], works=[work(11, 4, 20, 30)], trainer_pct=7, trainer_starts=60, prime_power=100.0),
        horse(8, "Wide Post", "12/1", "E/P", 5, [
            pp(36, "CLM", 10000, 77, 87, 86, 78, 4, 3.0, "4w, evenly", c1=3, c2=3, odds=10.0, cr=98),
            pp(66, "CLM", 10000, 78, 87, 86, 79, 5, 4.0, "wide trip", c1=3, c2=4, odds=12.0, cr=98),
        ], works=[work(9, 4, 7, 30)], trainer_pct=11, prime_power=110.0, post=8),
    ]
    races.append(race(4, "Clm 10000", "CLM", 10000, 8.0, "dirt", {"e1": 84, "e2": 83, "late": 82, "speed": 83}, r4))

    # R5: Allowance sprint 6f dirt, a standout (single leg for multi-race) with a short ML favourite.
    r5 = [
        horse(1, "Standout", "4/5", "E/P", 7, [
            pp(30, "ALW", 60000, 92, 96, 95, 82, 1, 0.0, "drew off, ridden out", c1=1, c2=1, odds=1.5, favorite=True, cr=110, lead_margin=4.0),
            pp(60, "ALW", 60000, 91, 95, 95, 81, 1, 0.0, "handily", c1=1, c2=1, odds=2.0, favorite=True, cr=110, lead_margin=3.0),
            pp(90, "OC", 40000, 90, 95, 94, 80, 2, 0.5, "dueled, just missed", c1=1, c2=1, odds=2.5, cr=108),
        ], works=[work(8, 5, 1, 30, True), work(18, 4, 2, 30)], trainer_pct=24, jockey_pct=21, prime_power=130.0,
            positives=["Highest last race speed rating", "Won last race (DMR 10/07 6f Dirt ft Alw60k)"]),
        horse(2, "Second Best", "3/1", "P", 3, [
            pp(28, "ALW", 60000, 85, 90, 90, 84, 3, 3.0, "rallied", c1=5, c2=4, odds=5.0, cr=110),
            pp(58, "ALW", 60000, 84, 89, 90, 83, 2, 2.0, "closed", c1=5, c2=5, odds=6.0, cr=110),
        ], works=[work(9, 4, 5, 30)], trainer_pct=15, prime_power=119.0),
        horse(3, "Third Wheel", "5/1", "E/P", 5, [
            pp(33, "ALW", 60000, 83, 92, 91, 80, 4, 4.0, "weakened", c1=2, c2=2, odds=8.0, cr=110),
            pp(63, "OC", 40000, 84, 92, 91, 80, 2, 1.0, "gamely", c1=2, c2=2, odds=4.0, cr=108),
        ], works=[work(10, 4, 8, 30)], trainer_pct=12, prime_power=117.0),
        horse(4, "Filler One", "10/1", "P", 2, [
            pp(40, "ALW", 60000, 80, 88, 88, 82, 5, 6.0, "no threat", c1=6, c2=6, odds=15.0, cr=110),
            pp(70, "ALW", 60000, 81, 88, 88, 81, 6, 7.0, "evenly", c1=6, c2=6, odds=18.0, cr=110),
        ], works=[work(12, 4, 12, 30)], trainer_pct=9, prime_power=110.0),
        horse(5, "Filler Two", "20/1", "S", 0, [
            pp(45, "CLM", 32000, 78, 85, 86, 80, 4, 5.0, "mild rally", c1=7, c2=7, odds=12.0, cr=106),
            pp(80, "CLM", 32000, 77, 84, 85, 80, 5, 6.0, "no factor", c1=7, c2=7, odds=14.0, cr=106),
        ], works=[work(14, 3, 15, 30)], trainer_pct=8, prime_power=105.0),
    ]
    races.append(race(5, "Alw 60000n2x", "ALW", None, 6.0, "dirt", {"e1": 94, "e2": 95, "late": 82, "speed": 86}, r5,
                      header="Alw 60000n2x 6 Furlongs 3&up Friday, November 06, 2026"))

    # R6: Stakes-ish OC 80k turf route, 9 horses, vulnerable favourite (E type into a hot pace with bounce risk).
    r6 = [
        horse(1, "Chalk Speed", "8/5", "E", 8, [
            pp(12, "OC", 80000, 96, 98, 97, 80, 1, 0.0, "drew off", surface="turf", c1=1, c2=1, odds=2.0, favorite=True, cr=112, lead_margin=3.0),
            pp(45, "OC", 80000, 88, 95, 94, 80, 2, 1.0, "pace, gamely", surface="turf", c1=1, c2=1, odds=3.0, cr=112),
            pp(80, "OC", 80000, 87, 95, 94, 79, 3, 2.0, "dueled, weakened", surface="turf", c1=1, c2=1, odds=4.0, cr=112),
        ], works=[], trainer_pct=20, jockey_pct=20, prime_power=128.0),
        horse(2, "Rival Speed", "6/1", "E", 7, [
            pp(30, "OC", 80000, 89, 97, 96, 79, 4, 3.0, "dueled, tired", surface="turf", c1=1, c2=1, odds=8.0, cr=112),
            pp(62, "OC", 80000, 90, 97, 96, 80, 2, 1.0, "set pace, caught", surface="turf", c1=1, c2=1, odds=6.0, cr=112),
        ], works=[work(10, 4, 4, 30)], trainer_pct=14, prime_power=120.0),
        horse(3, "Third Speed", "10/1", "E", 7, [
            pp(35, "OC", 80000, 86, 96, 95, 78, 5, 4.0, "vied, gave way", surface="turf", c1=2, c2=2, odds=12.0, cr=112),
            pp(70, "ALW", 60000, 87, 96, 95, 79, 3, 2.0, "pressed", surface="turf", c1=1, c2=2, odds=9.0, cr=110),
        ], works=[work(9, 4, 6, 30)], trainer_pct=12, prime_power=117.0),
        horse(4, "Stalk And Pounce", "4/1", "P", 4, [
            pp(28, "OC", 80000, 91, 88, 90, 90, 2, 0.5, "rallied, missed", surface="turf", c1=5, c2=4, odds=5.0, cr=112),
            pp(60, "OC", 80000, 90, 88, 90, 89, 1, 0.0, "driving", surface="turf", c1=5, c2=3, odds=4.0, cr=112, lead_margin=1.0),
            pp(95, "OC", 80000, 89, 87, 89, 88, 3, 1.5, "closed", surface="turf", c1=6, c2=5, odds=6.0, cr=112),
        ], works=[work(8, 5, 3, 30)], trainer_pct=18, jockey_pct=18, prime_power=125.0),
        horse(5, "Deep Closer", "5/1", "S", 0, [
            pp(32, "OC", 80000, 90, 82, 86, 94, 3, 1.5, "rallied widest", surface="turf", c1=9, c2=8, odds=7.0, cr=112),
            pp(66, "OC", 80000, 89, 82, 85, 93, 2, 0.5, "closed fast", surface="turf", c1=9, c2=9, odds=8.0, cr=112),
        ], works=[work(11, 4, 5, 30)], trainer_pct=15, prime_power=123.0),
        horse(6, "Mid Pack", "8/1", "P", 3, [
            pp(26, "OC", 80000, 87, 88, 89, 86, 4, 3.5, "evenly", surface="turf", c1=5, c2=5, odds=10.0, cr=112),
            pp(58, "OC", 80000, 88, 88, 89, 87, 5, 4.0, "mild bid", surface="turf", c1=5, c2=5, odds=12.0, cr=112),
        ], works=[work(9, 4, 9, 30)], trainer_pct=11, prime_power=118.0),
        horse(7, "Long Shot", "20/1", "S", 1, [
            pp(40, "OC", 50000, 83, 84, 86, 84, 6, 6.0, "no factor", surface="turf", c1=8, c2=8, odds=25.0, cr=108),
            pp(75, "OC", 50000, 84, 84, 86, 85, 7, 7.0, "outrun", surface="turf", c1=8, c2=8, odds=30.0, cr=108),
        ], works=[work(12, 4, 14, 30)], trainer_pct=9, prime_power=108.0),
        horse(8, "Ship In", "12/1", "E/P", 5, [
            pp(38, "ALW", 60000, 88, 94, 93, 82, 1, 0.0, "handily", surface="turf", c1=2, c2=1, odds=4.0, cr=110, lead_margin=2.0, track="SA"),
            pp(70, "ALW", 60000, 86, 93, 92, 81, 2, 1.0, "gamely", surface="turf", c1=2, c2=2, odds=5.0, cr=110, track="SA"),
        ], works=[work(10, 5, 2, 30)], trainer_pct=17, prime_power=119.0),
        horse(9, "Blinkers Boy", "15/1", "P", 2, [
            pp(30, "OC", 80000, 85, 89, 90, 85, 6, 5.0, "rank early, tired", surface="turf", c1=4, c2=4, odds=15.0, cr=112),
            pp(60, "OC", 80000, 86, 89, 90, 86, 5, 4.0, "no response", surface="turf", c1=4, c2=5, odds=14.0, cr=112),
        ], works=[work(8, 4, 10, 30)], trainer_pct=13, prime_power=112.0, blinkers="on",
            angles=[stat("1stTimeBlinkers", 25, 16, 40, 0.1)]),
    ]
    races.append(race(6, "OC 80000n1x", "OC", 80000, 8.0, "turf", {"e1": 84, "e2": 84, "late": 82, "speed": 84}, r6,
                      header="OC 80000n1x 1 Mile (T) 3&up Friday, November 06, 2026",
                      bias={"meet": {"races": 30, "runstyle": {"E": {"impact": 0.7}, "E/P": {"impact": 1.0}, "P": {"impact": 1.15}, "S": {"impact": 1.4}},
                                     "post": {"RAIL": {"impact": 1.0}, "1-3": {"impact": 1.0}, "4-7": {"impact": 1.0}, "8+": {"impact": 0.9}}},
                            "week": {"races": 2, "runstyle": {}, "post": {}}}))

    return {"source": "synthetic", "track": TRACK, "track_code": TRK, "date": TODAY.isoformat(), "races": races, "warnings": []}


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "synthetic_card.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(build_card(), fh, indent=1)
    print("wrote", out)
