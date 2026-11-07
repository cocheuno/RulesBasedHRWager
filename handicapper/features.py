"""
Derived, field-relative features for every horse in a race.

Everything the rules consume is computed here, once, so that each rule is a
small pure function of (horse_features, race_context).  All values are plain
Python numbers / None so the result is JSON-serialisable and auditable.
"""
from __future__ import annotations

import re
from statistics import mean

# ---------------------------------------------------------------------------
# Class ladder: a monotone numeric "level" so class moves can be compared.
# Higher = tougher.  Calibrated for Southern California circuit conventions.
# ---------------------------------------------------------------------------


def class_level(code: str | None, price: int | None, race_type: str = "") -> float | None:
    if code is None:
        return None
    rt = race_type or ""
    p = price or 0
    if code == "MCL":
        return 10.0 + min(p, 100000) / 10000.0          # MC12500=11.25, MC50000=15
    if code == "MSW":
        return 20.0 + min(p, 150000) / 50000.0          # Mdn 65k ~21.3, Mdn 100k=22
    if code == "MOC":
        return 20.5 + min(p, 100000) / 20000.0
    if code == "CLM":
        lvl = 20.0 + min(p, 100000) / 5000.0           # Clm 10000=22, 25000=25, 50000=30
        if re.search(r"n2L|n3L", rt):
            lvl -= 1.0
        return lvl
    if code == "STR":
        return 27.0
    if code == "OC":
        lvl = 30.0 + min(p, 200000) / 10000.0          # OC20k=32, 50k=35, 80k=38
        if "n1x" in rt or "N" in rt[-2:]:
            pass
        if re.search(r"n2x|n3x", rt):
            lvl += 1.5
        return lvl
    if code == "ALW":
        lvl = 34.0
        if re.search(r"n2x|n3x", rt):
            lvl += 2.0
        return lvl
    if code == "HCP":
        return 44.0
    if code == "STK":
        if re.search(r"-G1", rt):
            return 56.0
        if re.search(r"-G2", rt):
            return 52.0
        if re.search(r"-G3", rt):
            return 48.0
        if re.search(r"[LB]\s*\d", rt) or re.search(r"[LB]\d", rt):
            return 42.0
        return 44.0
    return None


TROUBLE_WORDS = [
    r"bump", r"bmp", r"stead", r"stdy", r"check", r"chk", r"block", r"blkd", r"shuffl", r"lost whip",
    r"\b[4-7]-?w", r"\b[4-7]wd", r"\b[4-7]wide", r"no room", r"lacked room", r"lack rm", r"alter", r"bobbl",
    r"stumbl", r"stmbl", r"off slow", r"slow st", r"broke slow", r"stp slw", r"step slow", r"pinch", r"squeez",
    r"fractious", r"\brank\b", r"clipped heels", r"heels", r"hesitat", r"brush", r"crowd", r"tight", r"tght",
    r"traffic", r"traffc", r"impeded", r"took up", r"lost path", r"bpd", r"shftd", r"shifted", r"in tight",
    r"hopped", r"ducked", r"drift", r"drft", r"lugged", r"wide trip", r"swung wide", r"angled wide", r"widest",
]
STRONG_WIN_WORDS = [r"drew off", r"driving", r"handily", r"easily", r"ridden out", r"going away", r"widened",
                    r"kicked clear", r"much the best", r"\bbest\b", r"drew clear", r"in hand", r"dominant", r"romp"]
GOOD_EFFORT_WORDS = [r"rallied", r"rally", r"closed", r"gamely", r"game", r"willing", r"surged", r"bid", r"dueled",
                     r"held", r"just missed", r"missed", r"nipped", r"outkicked", r"outfinished", r"improved", r"up for",
                     r"late", r"finished well", r"strong"]
# comment fragments that show the horse was involved in the early pace fight (Brisnet abbreviates heavily)
DUEL_WORDS = [r"duel", r"vied", r"\bpress", r"\bprss", r"battl", r"fought", r"contest", r"disput", r"hustled",
              r"set pace", r"\bled\b", r"\bpace\b"]
BAD_EFFORT_WORDS = [r"no factor", r"no threat", r"no rally", r"no response", r"no menace", r"empty", r"faded", r"tired",
                    r"weakened", r"wknd", r"stopped", r"eased", r"outrun", r"far back", r"dropped back", r"gave way",
                    r"retreated", r"flatten", r"done early", r"trailed", r"no speed", r"never involved", r"lost whip"]


def _has(words, text: str) -> bool:
    t = (text or "").lower()
    return any(re.search(w, t) for w in words)


def _clean_pp(h: dict) -> list[dict]:
    """PP lines that carry Brisnet figures and a finish."""
    return [p for p in h["pp"] if not p.get("dnf") and p.get("finish_pos") is not None]


def _figs(h: dict, key: str, n: int = 3) -> list:
    out = []
    for p in h["pp"]:
        if p.get("dnf"):
            continue
        v = p.get(key)
        if v is not None:
            out.append(v)
        if len(out) >= n:
            break
    return out


def _days_between(d1: str, d2: str) -> int | None:
    from datetime import date
    try:
        return (date.fromisoformat(d1) - date.fromisoformat(d2)).days
    except Exception:
        return None


def horse_features(h: dict, race: dict) -> dict:
    f: dict = {}
    pp = h["pp"]
    clean = _clean_pp(h)
    summ = h.get("summary") or {}
    life = h["records"].get("life") or {}
    f["starts"] = life.get("starts", len(pp))
    f["wins"] = life.get("win", 0)
    f["places"] = life.get("place", 0)
    f["shows"] = life.get("show", 0)
    f["itm_pct"] = round(100.0 * (f["wins"] + f["places"] + f["shows"]) / f["starts"], 1) if f["starts"] else None
    f["win_pct"] = round(100.0 * f["wins"] / f["starts"], 1) if f["starts"] else None
    f["first_time_starter"] = f["starts"] == 0
    f["is_maiden"] = f["wins"] == 0

    # ---- speed figures (surface-aware: an off-surface last race is excused when the horse has run on
    #      today's surface before; the S rules then read its most recent same-surface lines)
    surf_clean = [p for p in clean if p["surface"] == race["surface"]]
    last_line = clean[0] if clean else None
    f["last_off_surface"] = bool(last_line and last_line["surface"] != race["surface"])
    f["surface_form_lines"] = len(surf_clean)
    surf_spd = [p["speed"] for p in surf_clean if p.get("speed") is not None]
    # switch only with 2+ same-surface lines AND an off-surface figure below the horse's same-surface form
    # (a good race on the wrong surface is still evidence of form; a poor one is the excuse)
    f["use_surface_figs"] = bool(f["last_off_surface"] and len(surf_spd) >= 2 and last_line.get("speed") is not None
                                 and last_line["speed"] < max(surf_spd[:3]))
    if f["use_surface_figs"]:
        spd3 = [p["speed"] for p in surf_clean if p.get("speed") is not None][:3]
        allspd = [p["speed"] for p in surf_clean if p.get("speed") is not None][:10]
        f["off_surface_speed"] = last_line.get("speed")
    else:
        spd3 = _figs(h, "speed", 3)
        allspd = _figs(h, "speed", 10)
        f["off_surface_speed"] = None
    f["last_speed"] = spd3[0] if spd3 else None
    f["speed_last3"] = spd3
    f["best_last3"] = max(spd3) if spd3 else None
    f["avg_last3"] = round(mean(spd3), 1) if spd3 else None
    f["best_speed_10"] = max(allspd) if allspd else None
    f["prev_best"] = max(allspd[1:]) if len(allspd) > 1 else None
    f["career_top_last"] = (f["last_speed"] is not None and f["prev_best"] is not None and f["last_speed"] >= f["prev_best"] + 5)
    f["improving"] = len(spd3) == 3 and spd3[0] > spd3[1] > spd3[2]
    f["declining"] = len(spd3) == 3 and spd3[0] < spd3[1] < spd3[2]
    # speed on today's surface / at today's distance category
    surf_key = {"turf": "trf", "aw": "aw"}.get(race["surface"], "fst")
    f["best_surface_speed"] = (h["records"].get(surf_key) or {}).get("best_speed")
    f["surface_starts"] = (h["records"].get(surf_key) or {}).get("starts", 0)
    f["surface_wins"] = (h["records"].get(surf_key) or {}).get("win", 0)
    f["surface_itm"] = sum((h["records"].get(surf_key) or {}).get(k, 0) for k in ("win", "place", "show"))
    f["dist_starts"] = (h["records"].get("dis") or {}).get("starts", 0)
    f["dist_wins"] = (h["records"].get("dis") or {}).get("win", 0)
    f["dist_itm"] = sum((h["records"].get("dis") or {}).get(k, 0) for k in ("win", "place", "show"))
    f["dist_best_speed"] = (h["records"].get("dis") or {}).get("best_speed")
    f["track_starts"] = (h["records"].get("track") or {}).get("starts", 0)
    f["track_wins"] = (h["records"].get("track") or {}).get("win", 0)
    f["track_itm"] = sum((h["records"].get("track") or {}).get(k, 0) for k in ("win", "place", "show"))
    # speed figs earned in races matching today's surface and route/sprint category
    match = [p["speed"] for p in clean if p.get("speed") is not None and p["surface"] == race["surface"]
             and p["is_route"] == race["is_route"]]
    f["match_speeds"] = match[:3]
    f["best_match_speed"] = max(match[:4]) if match else None
    f["avg_match_speed"] = round(mean(match[:3]), 1) if match else None

    # ---- pace figures
    f["e1_last3"] = _figs(h, "e1", 3)
    f["e2_last3"] = _figs(h, "e2", 3)
    f["lp_last3"] = _figs(h, "lp", 3)
    f["best_e1"] = summ.get("best_e1") or (max(f["e1_last3"]) if f["e1_last3"] else None)
    f["best_e2"] = summ.get("best_e2") or (max(f["e2_last3"]) if f["e2_last3"] else None)
    f["best_lp"] = summ.get("best_late") or (max(f["lp_last3"]) if f["lp_last3"] else None)
    f["avg_e1"] = round(mean(f["e1_last3"]), 1) if f["e1_last3"] else None
    f["avg_e2"] = round(mean(f["e2_last3"]), 1) if f["e2_last3"] else None
    f["avg_lp"] = round(mean(f["lp_last3"]), 1) if f["lp_last3"] else None
    f["run_style"] = h["run_style"]
    f["speed_pts"] = h["speed_pts"] if h["speed_pts"] is not None else 0
    f["early_type"] = h["run_style"] in ("E", "E/P")
    f["closer_type"] = h["run_style"] in ("P", "S")

    # ---- class
    f["today_level"] = class_level(race["class_code"], race.get("claiming_price"), race.get("class_text", ""))
    last = clean[0] if clean else (pp[0] if pp else None)
    f["last"] = last
    f["last_level"] = class_level(last["class_code"], last.get("race_purse_or_price"), last.get("race_type", "")) if last else None
    f["class_move"] = (f["today_level"] - f["last_level"]) if (f["today_level"] is not None and f["last_level"] is not None) else None
    cr3 = _figs(h, "class_rating", 3)
    rr3 = _figs(h, "race_rating", 3)
    f["class_rating_last3"] = cr3
    f["avg_class_rating"] = round(mean(cr3), 1) if cr3 else None
    f["best_class_rating"] = max(cr3) if cr3 else None
    f["race_rating_last"] = rr3[0] if rr3 else None
    f["avg_race_rating"] = round(mean(rr3), 1) if rr3 else None
    f["acl"] = summ.get("acl")
    f["prime_power"] = h.get("prime_power")
    f["prime_power_rank"] = h.get("prime_power_rank")

    # ---- form / last race
    f["days_since"] = h.get("days_since_last")
    f["last_finish"] = last["finish_pos"] if last else None
    f["last_beaten"] = last.get("beaten_lengths") if last else None
    f["last_won"] = bool(last and last.get("won"))
    f["last_itm"] = bool(last and last.get("finish_pos") and last["finish_pos"] <= 3)
    f["last_field"] = last.get("field_size") if last else None
    f["last_odds"] = last.get("odds") if last else None
    f["last_comment"] = last.get("comment", "") if last else ""
    f["last_trouble"] = _has(TROUBLE_WORDS, f["last_comment"])
    f["last_strong_win"] = f["last_won"] and _has(STRONG_WIN_WORDS, f["last_comment"])
    f["last_good_effort"] = _has(GOOD_EFFORT_WORDS, f["last_comment"])
    f["last_bad_effort"] = _has(BAD_EFFORT_WORDS, f["last_comment"])
    f["last_same_surface"] = bool(last and last["surface"] == race["surface"])
    f["last_same_category"] = bool(last and last["is_route"] == race["is_route"])
    f["last_wide"] = bool(re.search(r"\b[4-7]-?w|\b[4-7]wd|\b[4-7]wide|widest", f["last_comment"].lower()))
    f["last_gained_late"] = bool(last and last.get("stretch", {}).get("pos") and last.get("finish_pos")
                                 and last["stretch"]["pos"] > last["finish_pos"])
    f["last_closed_lengths"] = None
    if last and last.get("call2", {}).get("lengths") is not None and last.get("beaten_lengths") is not None:
        f["last_closed_lengths"] = round(last["call2"]["lengths"] - last["beaten_lengths"], 2)
    # last-race pace context: did it run against the bias (duel) ?
    f["last_led_early"] = bool(last and last.get("call1", {}).get("pos") == 1)
    # consecutive ITM
    f["itm_streak"] = 0
    for p in clean:
        if p["finish_pos"] <= 3:
            f["itm_streak"] += 1
        else:
            break
    # 2nd/3rd off the layoff: count starts since the most recent 60+ day break *visible in the PPs*.
    # If no such break is shown, the value is None (unknown / no layoff) - a lightly raced horse with two
    # tightly spaced starts is simply making its third start, not its "2nd off a layoff".
    f["races_since_layoff"] = summ.get("races_since_layoff")
    if f["races_since_layoff"] is None and len(clean) >= 2:
        n, found = 0, False
        for i in range(len(clean) - 1):
            gap = _days_between(clean[i]["date"], clean[i + 1]["date"])
            if gap is not None and gap > 60:
                found = True
                break
            n += 1
        f["races_since_layoff"] = n if found else None
    # works
    works = h.get("workouts", [])
    f["num_works"] = len(works)
    f["bullet_works"] = sum(1 for w in works if w.get("bullet"))
    f["recent_fast_works"] = sum(1 for w in works[:4] if w.get("of") and w["rank"] <= max(2, int(0.15 * w["of"])))
    f["works_since_last"] = _works_since_last(h)
    f["has_work_5f_or_more"] = any(w["distance_furlongs"] >= 5 for w in works[:4])

    # ---- connections
    f["trainer_year"] = _stat(h["trainer_stats"], r"^\d{4}$")
    f["jockey_year"] = _stat(h["jockey_stats"], r"^\d{4}$")
    f["jt_combo"] = _stat(h["jockey_stats"], r"Trn L60")
    f["trainer_angles"] = [t for t in h["trainer_stats"] if not re.fullmatch(r"\d{4}", t["category"])]
    f["trainer_flagged"] = [t for t in f["trainer_angles"] if t.get("flag")]
    f["trainer_meet"] = h.get("trainer_meet") or {}
    f["jockey_meet"] = h.get("jockey_meet") or {}
    f["jockey_switch"] = bool(last and h.get("jockey") and _jockey_key(h["jockey"]) != _jockey_key(last.get("jockey", "")))

    # ---- equipment / meds / pedigree
    f["blinkers_on"] = h.get("blinkers_change") == "on"
    f["blinkers_off"] = h.get("blinkers_change") == "off"
    f["first_lasix"] = bool(h.get("first_lasix"))
    pr = h.get("pedigree_ratings") or {}
    f["ped_surface_rating"] = _rating(pr.get(surf_key))
    f["ped_dist_rating"] = _rating(pr.get("dis"))
    f["ped_off_rating"] = _rating(pr.get("off"))
    ps = h.get("pedigree_stats") or {}
    f["sire_awd"] = (ps.get("sire") or {}).get("awd")
    f["damsire_awd"] = (ps.get("dam_sire") or {}).get("awd")
    f["sire_first_pct"] = (ps.get("sire") or {}).get("first_pct")
    f["sire_mud_pct"] = (ps.get("sire") or {}).get("mud_pct")
    f["dam_dpi"] = (ps.get("dam") or {}).get("dpi")
    f["sire_spi"] = (ps.get("sire") or {}).get("spi")

    # ---- expert trip / intent / condition-book features (consumed by S9, C6-C10, P9, F11-F15, M4)
    par = (race.get("pars") or {}).get("speed")
    last3 = clean[:3]
    f["trouble_last3"] = sum(1 for p in last3 if _has(TROUBLE_WORDS, p.get("comment", ""))
                             and p.get("beaten_lengths") is not None and p["beaten_lengths"] <= 5)
    f["last_dueled"] = _has(DUEL_WORDS, f["last_comment"]) or bool(
        last and last.get("call1", {}).get("pos") in (1, 2) and last.get("call1", {}).get("lengths") is not None
        and last["call1"]["lengths"] <= 1.0)
    f["last_favorite"] = bool(last and last.get("favorite"))
    f["last_beaten_favorite"] = f["last_favorite"] and not f["last_won"]
    f["last_claimed"] = bool(last and last.get("claimed"))
    f["last_claim_price"] = (last.get("race_purse_or_price") if (last and f["last_claimed"]) else None)
    f["today_claiming_price"] = race.get("claiming_price")
    f["prior_claiming_starts"] = sum(1 for p in pp if p.get("class_code") in ("CLM", "MCL"))
    f["first_time_for_tag"] = bool(race.get("class_code") == "CLM" and len(pp) >= 2 and f["prior_claiming_starts"] == 0)
    f["last_maiden_win"] = bool(f["last_won"] and last and last.get("class_code") in ("MSW", "MCL", "MOC"))
    f["last_maiden_win_claiming"] = bool(f["last_maiden_win"] and last.get("class_code") == "MCL")
    ct = race.get("class_text") or ""
    f["today_n1x"] = bool(re.search(r"n1x|nw1|N1X|n1y", ct))
    f["today_n2l"] = bool(re.search(r"n2L|n2l|N2L", ct))
    f["last_speed_vs_par"] = (f["last_speed"] - par) if (par is not None and f["last_speed"] is not None) else None
    f["paired_figs"] = len(spd3) >= 2 and abs(spd3[0] - spd3[1]) <= 2
    f["best_two_recent"] = max(spd3[:2]) if spd3 else None
    # back class: has the horse already been competitive at a level above today's (last 10 starts)?
    lv = [(class_level(p["class_code"], p.get("race_purse_or_price"), p.get("race_type", "")), p) for p in clean[:10]]
    comp = [l for l, p in lv if l is not None and p.get("beaten_lengths") is not None and p["beaten_lengths"] <= 2]
    f["best_competitive_level"] = max(comp) if comp else None
    comp3 = [l for l, p in lv[:3] if l is not None and p.get("beaten_lengths") is not None and p["beaten_lengths"] <= 2]
    f["back_class"] = bool(f["today_level"] is not None and f["best_competitive_level"] is not None
                           and f["best_competitive_level"] >= f["today_level"] + 2
                           and not any(l >= f["today_level"] for l in comp3))
    f["freshened"] = bool(f["days_since"] is not None and 28 <= f["days_since"] <= 60 and f["declining"]
                          and f["works_since_last"] >= 2)
    f["last_lost_fast"] = bool(not f["last_won"] and f["last_speed_vs_par"] is not None and f["last_speed_vs_par"] >= 2
                               and f["last_beaten"] is not None and f["last_beaten"] >= 4)
    f["debut_speed"] = spd3[-1] if (f["starts"] == 1 and spd3) else None

    # ---- Brisnet Power Play sheet angles (pick.py --sheet), if the sheet was supplied
    f["sheet_angles"] = list(h.get("sheet_angles") or [])
    f["key_race"] = any(a.replace(" ", "") == "ExitKeyRace" for a in f["sheet_angles"])
    f["possible_key_race"] = any(a.replace(" ", "") == "ExitPossibleKeyRace" for a in f["sheet_angles"])
    # ---- Brisnet QuickPlay comments
    f["positives"] = h.get("positives", [])
    f["negatives"] = h.get("negatives", [])
    f["ml_decimal"] = h.get("ml_decimal")
    f["post"] = h.get("post") or (int(re.sub(r"\D", "", h["pgm"])) if h.get("pgm") else None)
    f["entry_status"] = h.get("entry_status")
    f["age"] = h.get("age")
    f["sex"] = h.get("sex")
    f["weight"] = h.get("weight")
    f["name"] = h["name"]
    f["pgm"] = h["pgm"]
    f["turf_to_dirt"] = bool(last and last["surface"] == "turf" and race["surface"] == "dirt")
    f["dirt_to_turf"] = bool(last and last["surface"] == "dirt" and race["surface"] == "turf")
    f["sprint_to_route"] = bool(last and (not last["is_route"]) and race["is_route"])
    f["route_to_sprint"] = bool(last and last["is_route"] and not race["is_route"])
    f["num_clean_pp"] = len(clean)
    f["_pp3"] = [dict(p, _level=class_level(p["class_code"], p.get("race_purse_or_price"), p.get("race_type", ""))) for p in clean[:3]]
    f["_works"] = works
    return f


def _works_since_last(h: dict) -> int:
    """Number of workouts dated after the last race (approximate: compares day-month within a year)."""
    if not h["pp"] or not h.get("workouts"):
        return len(h.get("workouts", []))
    last = h["pp"][0]["date"]  # YYYY-MM-DD
    from datetime import date
    try:
        ld = date.fromisoformat(last)
    except Exception:
        return 0
    months = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6, "Jly": 7, "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
    n = 0
    for w in h["workouts"]:
        m = re.match(r"(\d{2})([A-Z][a-z]{2})(?:'(\d{2}))?", w["date"])
        if not m:
            continue
        yr = 2000 + int(m.group(3)) if m.group(3) else ld.year if months[m.group(2)] >= ld.month else ld.year + 1
        try:
            wd = date(yr, months[m.group(2)], int(m.group(1)))
        except ValueError:
            continue
        if wd > ld:
            n += 1
    return n


def _stat(stats: list, pattern: str) -> dict | None:
    for s in stats:
        if re.search(pattern, s["category"]):
            return s
    return None


def _jockey_key(name: str) -> str:
    """'Frey Kyle' / 'FreyK' -> 'freyk' (surname + first initial)."""
    n = re.sub(r"[^A-Za-z ]", "", name or "").strip()
    if " " in n:
        parts = n.split()
        return (parts[0] + parts[-1][0]).lower() if len(parts) > 1 else parts[0].lower()
    return n.lower()


def _rating(s: str | None) -> int | None:
    if not s:
        return None
    m = re.match(r"(\d+)", s)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Race context: field-relative ranks and pace scenario
# ---------------------------------------------------------------------------
def race_context(race: dict, feats: dict[str, dict]) -> dict:
    ctx: dict = {"race": race, "n": len(feats)}
    pars = race.get("pars") or {}
    ctx["par_speed"] = pars.get("speed")
    ctx["par_e1"] = pars.get("e1")
    ctx["par_e2"] = pars.get("e2")
    ctx["par_late"] = pars.get("late")

    def rank_of(key, higher_is_better=True):
        vals = [(pgm, f[key]) for pgm, f in feats.items() if f.get(key) is not None]
        vals.sort(key=lambda x: x[1], reverse=higher_is_better)
        ranks, top = {}, (vals[0][1] if vals else None)
        prev_val, prev_rank = None, 0
        for i, (pgm, v) in enumerate(vals, 1):
            r = prev_rank if v == prev_val else i
            ranks[pgm] = r
            prev_val, prev_rank = v, r
        return ranks, top, (vals[1][1] if len(vals) > 1 else None)

    for key in ("last_speed", "best_last3", "avg_last3", "best_match_speed", "best_surface_speed", "dist_best_speed",
                "prime_power", "avg_class_rating", "best_class_rating", "best_e1", "best_e2", "best_lp", "avg_e1",
                "avg_lp", "speed_pts", "race_rating_last", "acl", "itm_pct"):
        ranks, top, second = rank_of(key)
        ctx[f"rank_{key}"] = ranks
        ctx[f"top_{key}"] = top
        ctx[f"second_{key}"] = second
    # pace scenario
    early = [(pgm, f) for pgm, f in feats.items() if f["run_style"] in ("E", "E/P")]
    e_only = [(pgm, f) for pgm, f in feats.items() if f["run_style"] == "E"]
    ctx["num_early"] = len(early)
    ctx["num_E"] = len(e_only)
    ctx["num_high_pts"] = sum(1 for f in feats.values() if f["speed_pts"] >= 6)
    sp = sorted(((f["speed_pts"], pgm) for pgm, f in feats.items()), reverse=True)
    ctx["lone_speed"] = None
    if sp and sp[0][0] >= 5 and (len(sp) == 1 or sp[0][0] - sp[1][0] >= 2) and ctx["num_E"] <= 1:
        ctx["lone_speed"] = sp[0][1]
    if ctx["num_E"] >= 3 or ctx["num_high_pts"] >= 3:
        ctx["pace_shape"] = "hot"
    elif ctx["lone_speed"]:
        ctx["pace_shape"] = "lone"
    elif ctx["num_early"] <= 2:
        ctx["pace_shape"] = "soft"
    else:
        ctx["pace_shape"] = "honest"
    ctx["best_last3_by_pgm"] = {pgm: f["best_last3"] for pgm, f in feats.items()}
    # probable pace leader by Brisnet E1 figure (Brohamer / Sartin "pace line" matchup)
    e1s = sorted(((f["avg_e1"], pgm, f["run_style"]) for pgm, f in feats.items()
                  if f["avg_e1"] is not None and f["run_style"] in ("E", "E/P")), reverse=True)
    ctx["e1_leaders"] = [{"pgm": pgm, "avg_e1": v, "run_style": rs} for v, pgm, rs in e1s]
    # morning-line favourite (lowest ML)
    mls = [(f["ml_decimal"], pgm) for pgm, f in feats.items() if f.get("ml_decimal") is not None]
    ctx["ml_favorite"] = min(mls)[1] if mls else None
    ctx["ml_favorite_odds"] = min(mls)[0] if mls else None
    ctx["day_bias"] = race.get("day_bias")   # from handicapper.results.attach_day_bias (pick.py --results)
    # bias
    bias = race.get("bias") or {}
    ctx["bias_meet"] = bias.get("meet") or {}
    ctx["bias_week"] = bias.get("week") or {}
    ctx["field_size"] = len(feats)
    ws = [f["weight"] for f in feats.values() if f.get("weight")]
    ctx["max_weight"] = max(ws) if ws else None
    ctx["has_older"] = any((f.get("age") or 0) >= 4 for f in feats.values())
    try:
        race["date_month"] = int((race.get("race_date") or "2000-11-01").split("-")[1])
    except Exception:
        race["date_month"] = 11
    return ctx
