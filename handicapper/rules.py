"""
Handicapping rule catalog.

Every rule is a pure function  rule(f, ctx) -> None | (factor, note)
where `f` is the horse's feature dict (features.horse_features) and `ctx`
the race context (features.race_context).  The engine multiplies `factor`
by the rule's weight (default here, overridable from rules_config.json)
and records the note, so every point on the scoresheet is traceable to a
named rule.

Rule ids are stable: S = speed, C = class, P = pace, F = form, K = connections,
D = distance/surface, E = equipment, Q = Brisnet QuickPlay comments,
M = maidens/first-timers, X = eliminations (hard filters), V = value/odds.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

RULES: list["Rule"] = []


@dataclass
class Rule:
    id: str
    name: str
    category: str
    weight: float
    fn: Callable
    doc: str
    hard: bool = False   # hard rules eliminate (factor < 0) or are informational


def rule(id: str, name: str, category: str, weight: float, hard: bool = False):
    def deco(fn):
        RULES.append(Rule(id, name, category, weight, fn, (fn.__doc__ or "").strip(), hard))
        return fn
    return deco


def _n(x, default=None):
    return default if x is None else x


# =========================================================================
# S — SPEED FIGURES
# =========================================================================
@rule("S1", "Top last-race speed figure", "speed", 6)
def s1(f, ctx):
    """Highest Brisnet speed figure in the field last time out: full credit; within 2 points of the top: half."""
    if f["last_speed"] is None or ctx["top_last_speed"] is None:
        return None
    if f["last_speed"] == ctx["top_last_speed"]:
        return 1.0, f"last speed {f['last_speed']} is top in field"
    if f["last_speed"] >= ctx["top_last_speed"] - 2:
        return 0.5, f"last speed {f['last_speed']} within 2 of top ({ctx['top_last_speed']})"
    return None


@rule("S2", "Best of last three speed figures", "speed", 6)
def s2(f, ctx):
    """Best Brisnet speed figure among the last three starts ranks 1st (1.0), 2nd (0.6) or 3rd (0.3) in the field."""
    r = ctx["rank_best_last3"].get(f["pgm"])
    if r == 1:
        return 1.0, f"best-of-last-3 {f['best_last3']} ranks 1st"
    if r == 2:
        return 0.6, f"best-of-last-3 {f['best_last3']} ranks 2nd"
    if r == 3:
        return 0.3, f"best-of-last-3 {f['best_last3']} ranks 3rd"
    return None


@rule("S3", "Average speed vs. class par", "speed", 5)
def s3(f, ctx):
    """Average of the last three speed figures compared with the Brisnet PAR for today's class:
    >= par +3: 1.0; >= par: 0.5; par-4 .. par-1: 0; below par-4: -0.6; below par-8: -1.0."""
    par = ctx["par_speed"]
    if par is None or f["avg_last3"] is None:
        return None
    d = f["avg_last3"] - par
    if d >= 3:
        return 1.0, f"avg last-3 {f['avg_last3']} is {d:+.0f} vs par {par}"
    if d >= 0:
        return 0.5, f"avg last-3 {f['avg_last3']} is {d:+.0f} vs par {par}"
    if d <= -8:
        return -1.0, f"avg last-3 {f['avg_last3']} is {d:+.0f} vs par {par}"
    if d <= -4:
        return -0.6, f"avg last-3 {f['avg_last3']} is {d:+.0f} vs par {par}"
    return None


@rule("S4", "Best figure on today's surface & distance category", "speed", 5)
def s4(f, ctx):
    """Best speed figure earned in races matching today's surface and sprint/route category ranks 1st (1.0) or 2nd (0.5).
    A horse with no matching race gets no credit here (handled by D-rules)."""
    r = ctx["rank_best_match_speed"].get(f["pgm"])
    if r == 1:
        return 1.0, f"best matching-conditions figure {f['best_match_speed']} ranks 1st"
    if r == 2:
        return 0.5, f"best matching-conditions figure {f['best_match_speed']} ranks 2nd"
    return None


@rule("S5", "Improving / declining figure pattern", "speed", 3)
def s5(f, ctx):
    """Three consecutively rising speed figures: +1.0 (horse is on an upward form cycle).
    Three consecutively falling figures: -1.0 (tailing off)."""
    if f["improving"]:
        return 1.0, f"figures rising {f['speed_last3'][::-1]}"
    if f["declining"]:
        return -1.0, f"figures falling {f['speed_last3'][::-1]}"
    return None


@rule("S6", "Bounce risk after a career-top figure", "speed", 3)
def s6(f, ctx):
    """Last race was a new career top by 5+ points over every previous figure AND the horse has 3+ starts:
    -1.0 (regression to the mean is likely, especially off a short rest)."""
    if f["career_top_last"] and f["starts"] >= 3:
        extra = f["days_since"] is not None and f["days_since"] < 21
        return (-1.0 if not extra else -1.3), f"career top {f['last_speed']} vs prior best {f['prev_best']}" + (" on short rest" if extra else "")
    return None


@rule("S7", "Prime Power rank", "speed", 7)
def s7(f, ctx):
    """Brisnet Prime Power rank in the field: 1st 1.0, 2nd 0.6, 3rd 0.35. Bonus +0.4 if the top-ranked horse
    is 4+ points clear of the second."""
    r = f.get("prime_power_rank")
    if r == 1:
        bonus = 0.0
        if ctx["second_prime_power"] is not None and f["prime_power"] - ctx["second_prime_power"] >= 4:
            bonus = 0.4
        return 1.0 + bonus, f"Prime Power {f['prime_power']} ranks 1st" + (" (clear)" if bonus else "")
    if r == 2:
        return 0.6, f"Prime Power {f['prime_power']} ranks 2nd"
    if r == 3:
        return 0.35, f"Prime Power {f['prime_power']} ranks 3rd"
    return None


@rule("S8", "Consistently near par", "speed", 3)
def s8(f, ctx):
    """All of the last three speed figures are within 3 points of today's par or better: 1.0 (reliable, no bounce risk)."""
    par = ctx["par_speed"]
    s = f["speed_last3"]
    if par and len(s) == 3 and all(v >= par - 3 for v in s):
        return 1.0, f"last 3 figures {s[::-1]} all >= par-3 ({par - 3})"
    return None


@rule("D7", "Best figure at the exact distance", "distance", 2)
def d7(f, ctx):
    """Brisnet 'best speed at distance' (Dis record) ranks 1st in the field: 1.0; 2nd: 0.5."""
    r = ctx["rank_dist_best_speed"].get(f["pgm"])
    if r == 1 and f["dist_best_speed"]:
        return 1.0, f"best at distance {f['dist_best_speed']}"
    if r == 2 and f["dist_best_speed"]:
        return 0.5, f"2nd best at distance {f['dist_best_speed']}"
    return None


# =========================================================================
# C — CLASS
# =========================================================================
@rule("C1", "Class drop", "class", 5)
def c1(f, ctx):
    """Today's class level is below the last race's (by the class ladder): drop of 1-3 levels 0.6,
    3+ levels 1.0.  If the horse was beaten 10+ lengths last time the drop is discounted to 0.3 ("dropping for a reason")."""
    m = f["class_move"]
    if m is None or m >= -0.5:
        return None
    fac = 1.0 if m <= -3 else 0.6
    if f["last_beaten"] is not None and f["last_beaten"] >= 10:
        fac = 0.3
    return fac, f"drops {abs(m):.1f} class levels" + (" (badly beaten last)" if fac == 0.3 else "")


@rule("C2", "Class rise", "class", 4)
def c2(f, ctx):
    """Today's class level is above the last race's: -0.6 for a 1-3 level rise, -1.0 for 3+.
    Waived (0) if the horse won last time by 2+ lengths or earned a figure above par."""
    m = f["class_move"]
    if m is None or m <= 0.5:
        return None
    if f["last_won"] and (f["last_beaten"] == 0 and _n(f["last_closed_lengths"], 0) is not None):
        last = f["last"]
        marg = last["top_finishers"][0]["margin_lengths"] if last and last.get("top_finishers") else None
        if marg is not None and marg >= 2:
            return 0.0, f"rises {m:.1f} levels but won by {marg}"
    if ctx["par_speed"] and f["last_speed"] is not None and f["last_speed"] >= ctx["par_speed"] + 2:
        return 0.0, f"rises {m:.1f} levels but last figure {f['last_speed']} beats par"
    return (-1.0 if m >= 3 else -0.6), f"rises {m:.1f} class levels"


@rule("C3", "Class rating rank", "class", 4)
def c3(f, ctx):
    """Average Brisnet class rating of the last three starts ranks 1st (1.0), 2nd (0.5) or 3rd (0.25)."""
    r = ctx["rank_avg_class_rating"].get(f["pgm"])
    if r == 1:
        return 1.0, f"avg class rating {f['avg_class_rating']} ranks 1st"
    if r == 2:
        return 0.5, f"avg class rating {f['avg_class_rating']} ranks 2nd"
    if r == 3:
        return 0.25, f"avg class rating {f['avg_class_rating']} ranks 3rd"
    return None


@rule("C4", "Proven at today's level", "class", 3)
def c4(f, ctx):
    """Competitive (finished within 3 lengths) in a race whose class level was >= today's within the last 3 starts: 1.0."""
    last3 = [p for p in f.get("_pp3", [])]
    for p in last3:
        lvl = p.get("_level")
        if lvl is not None and f["today_level"] is not None and lvl >= f["today_level"] and p.get("beaten_lengths") is not None and p["beaten_lengths"] <= 3:
            return 1.0, f"within 3L at {p['race_type']} on {p['date']}"
    return None


@rule("C5", "Last race rating beats the field", "class", 3)
def c5(f, ctx):
    """Brisnet race rating of the last race (strength of the field it faced) ranks 1st: 1.0, 2nd: 0.5."""
    r = ctx["rank_race_rating_last"].get(f["pgm"])
    if r == 1:
        return 1.0, f"last race rating {f['race_rating_last']} ranks 1st"
    if r == 2:
        return 0.5, f"last race rating {f['race_rating_last']} ranks 2nd"
    return None


@rule("C6", "Claimed / protected drop", "class", 2)
def c6(f, ctx):
    """Horse is dropping in class off a claim (new barn moving it down) with a trainer winning >= 15%: 1.0."""
    last = f["last"]
    if last and last.get("claimed") and f["class_move"] is not None and f["class_move"] < 0:
        ty = f["trainer_year"] or {}
        if ty.get("win_pct", 0) >= 15:
            return 1.0, "dropped by new barn after claim"
    return None


# =========================================================================
# P — PACE
# =========================================================================
@rule("P1", "Lone early speed", "pace", 7)
def p1(f, ctx):
    """Only one horse in the field has early-speed points >= 5 and is at least 2 points clear of all others,
    with no other 'E' type: that horse gets 1.0 (uncontested lead).  Full credit on dirt, 0.7 on turf."""
    if ctx["lone_speed"] == f["pgm"]:
        return (1.0 if ctx["race"]["surface"] == "dirt" else 0.7), f"lone speed ({f['run_style']} {f['speed_pts']} pts)"
    return None


@rule("P2", "Speed duel penalty / closer bonus", "pace", 4)
def p2(f, ctx):
    """Hot pace shape (3+ 'E' types or 3+ horses with 6+ speed points): E types -1.0, E/P -0.5, P +0.5, S +1.0.
    Soft pace shape (<= 2 early types, no lone speed): E/E-P +0.4, S -0.4."""
    shape = ctx["pace_shape"]
    rs = f["run_style"]
    if shape == "hot":
        return {"E": -1.0, "E/P": -0.5, "P": 0.5, "S": 1.0}.get(rs, 0.0) or None, f"hot pace ({ctx['num_E']} E, {ctx['num_high_pts']} high-pts) vs {rs}"
    if shape == "soft":
        return {"E": 0.4, "E/P": 0.4, "S": -0.4}.get(rs, 0.0) or None, f"soft pace vs {rs}"
    return None


@rule("P3", "Best early pace figure (E1/E2)", "pace", 4)
def p3(f, ctx):
    """Best E2 pace figure in the field: 1.0 in sprints, 0.6 in routes; best E1 adds 0.4 (sprints only)."""
    pts = 0.0
    notes = []
    sprint = not ctx["race"]["is_route"]
    if ctx["rank_best_e2"].get(f["pgm"]) == 1:
        pts += 1.0 if sprint else 0.6
        notes.append(f"best E2 {f['best_e2']}")
    if sprint and ctx["rank_best_e1"].get(f["pgm"]) == 1:
        pts += 0.4
        notes.append(f"best E1 {f['best_e1']}")
    return (pts, ", ".join(notes)) if pts else None


@rule("P4", "Best late pace figure", "pace", 4)
def p4(f, ctx):
    """Best late-pace (LP) figure in the field: 1.0 in routes/turf, 0.6 in dirt sprints; 2nd best 0.4."""
    r = ctx["rank_best_lp"].get(f["pgm"])
    big = ctx["race"]["is_route"] or ctx["race"]["surface"] == "turf"
    if r == 1:
        return (1.0 if big else 0.6), f"best late pace {f['best_lp']}"
    if r == 2:
        return 0.4, f"2nd best late pace {f['best_lp']}"
    return None


@rule("P5", "Running style vs. track bias", "pace", 4)
def p5(f, ctx):
    """Brisnet track-bias impact value for the horse's run style at today's surface/distance (meet totals):
    >= 1.30: 1.0; 1.10-1.29: 0.5; <= 0.60: -1.0; 0.61-0.85: -0.5.  Weekly figures (if 5+ races) add half credit."""
    pts, notes = 0.0, []
    for key, scale, minr in (("bias_meet", 1.0, 10), ("bias_week", 0.5, 5)):
        b = ctx.get(key) or {}
        if (b.get("races") or 0) < minr:
            continue
        iv = ((b.get("runstyle") or {}).get(f["run_style"]) or {}).get("impact")
        if iv is None:
            continue
        if iv >= 1.30:
            pts += 1.0 * scale
        elif iv >= 1.10:
            pts += 0.5 * scale
        elif iv <= 0.60:
            pts -= 1.0 * scale
        elif iv <= 0.85:
            pts -= 0.5 * scale
        notes.append(f"{key[5:]} {f['run_style']} IV {iv}")
    pts = max(-1.0, min(1.0, pts))
    return (pts, ", ".join(notes)) if pts else None


@rule("P6", "Post position vs. bias", "pace", 2)
def p6(f, ctx):
    """Track-bias impact value for the post-position group (RAIL, 1-3, 4-7, 8+): >= 1.3: 1.0; <= 0.7: -1.0
    (meet totals). Rail horse with E/P or P style in a route adds nothing extra."""
    b = ctx.get("bias_meet") or {}
    post = f["post"]
    if not b.get("post") or post is None:
        return None
    grp = "RAIL" if post == 1 else ("1-3" if post <= 3 else ("4-7" if post <= 7 else "8+"))
    iv = (b["post"].get(grp) or {}).get("impact")
    if iv is None:
        return None
    if iv >= 1.3:
        return 1.0, f"post {post} ({grp}) IV {iv}"
    if iv <= 0.7:
        return -1.0, f"post {post} ({grp}) IV {iv}"
    return None


@rule("P7", "Early speed points rank", "pace", 2)
def p7(f, ctx):
    """Brisnet early-speed points: 7-8 points 1.0, 5-6 points 0.5 (only when the pace shape is not hot)."""
    if ctx["pace_shape"] == "hot":
        return None
    if f["speed_pts"] >= 7:
        return 1.0, f"{f['speed_pts']} speed points"
    if f["speed_pts"] >= 5:
        return 0.5, f"{f['speed_pts']} speed points"
    return None


@rule("P8", "Pace figures vs. par", "pace", 2.5)
def p8(f, ctx):
    """Early types: average E2 of last 3 >= par E2 + 2 in a soft/lone pace: +1.0 (can control the race).
    Closers: average late pace >= par late + 3 in a hot pace: +1.0 (will be running at the end).
    Early type whose average E2 is 6+ below par: -0.6 (will not be able to get position)."""
    if f["early_type"]:
        if f["avg_e2"] is None or ctx["par_e2"] is None:
            return None
        if ctx["pace_shape"] in ("soft", "lone") and f["avg_e2"] >= ctx["par_e2"] + 2:
            return 1.0, f"E2 avg {f['avg_e2']} vs par {ctx['par_e2']} in a {ctx['pace_shape']} pace"
        if f["avg_e2"] <= ctx["par_e2"] - 6:
            return -0.6, f"E2 avg {f['avg_e2']} vs par {ctx['par_e2']}"
        return None
    if f["closer_type"] and f["avg_lp"] is not None and ctx["par_late"] is not None:
        if ctx["pace_shape"] == "hot" and f["avg_lp"] >= ctx["par_late"] + 3:
            return 1.0, f"LP avg {f['avg_lp']} vs par {ctx['par_late']} into a hot pace"
    return None


# =========================================================================
# F — FORM
# =========================================================================
@rule("F1", "Won last race", "form", 3)
def f1(f, ctx):
    """Won last start: 1.0; won 'handily/drew off/driving' (strong win comment): 1.4."""
    if f["last_won"]:
        return (1.4 if f["last_strong_win"] else 1.0), "won last" + (" impressively" if f["last_strong_win"] else "")
    return None


@rule("F2", "In the money last race", "form", 2)
def f2(f, ctx):
    """Finished 2nd or 3rd last time beaten <= 3 lengths: 1.0; 4th-5th beaten <= 3 lengths: 0.5."""
    if f["last_finish"] is None or f["last_beaten"] is None or f["last_won"]:
        return None
    if f["last_finish"] <= 3 and f["last_beaten"] <= 3:
        return 1.0, f"finished {f['last_finish']}{'nd' if f['last_finish'] == 2 else 'rd'} beaten {f['last_beaten']}L"
    if f["last_finish"] <= 5 and f["last_beaten"] <= 3:
        return 0.5, f"{f['last_finish']}th beaten only {f['last_beaten']}L"
    return None


@rule("F3", "Troubled trip last out", "form", 3)
def f3(f, ctx):
    """Last-race comment shows trouble (bumped, steadied, checked, blocked, wide trip, slow start, etc.) and the
    horse still finished within 6 lengths: 1.0 (excuse); trouble and beaten > 6: 0.4."""
    if not f["last_trouble"]:
        return None
    if f["last_beaten"] is not None and f["last_beaten"] <= 6:
        return 1.0, f"trouble: '{f['last_comment']}'"
    return 0.4, f"trouble: '{f['last_comment']}'"


@rule("F4", "Closed ground late last out", "form", 2)
def f4(f, ctx):
    """Gained 2+ lengths from the second call to the finish last time, or passed horses in the stretch: 1.0."""
    if f["last_closed_lengths"] is not None and f["last_closed_lengths"] >= 2:
        return 1.0, f"closed {f['last_closed_lengths']}L from 2nd call"
    if f["last_gained_late"]:
        return 0.5, "passed horses in the stretch"
    return None


@rule("F5", "Bad effort last out", "form", 3)
def f5(f, ctx):
    """Last race comment is negative (faded, tired, no factor, eased, stopped...) and beaten 8+ lengths
    with no trouble: -1.0.  Beaten 15+: -1.5."""
    if f["last_beaten"] is None or f["last_trouble"]:
        return None
    if f["last_beaten"] >= 15:
        return -1.5, f"beaten {f['last_beaten']}L last"
    if f["last_bad_effort"] and f["last_beaten"] >= 8:
        return -1.0, f"'{f['last_comment']}' beaten {f['last_beaten']}L"
    return None


@rule("F6", "Layoff handling", "form", 3)
def f6(f, ctx):
    """Days since last race: 46-90 days with a flagged/positive layoff trainer stat (win% >= 15): +0.5;
    91-180 days: -0.3 unless 3+ works incl. a 5f+ work (then 0); 181+ days: -1.0 unless trainer layoff stat
    >= 18% and 4+ works (then -0.3).  <= 14 days ('quick back'): +0.3 if last race was good."""
    d = f["days_since"]
    if d is None:
        return None
    lay = [t for t in f["trainer_angles"] if re.search(r"days|Away|layoff|Layoff", t["category"])]
    best = max((t["win_pct"] for t in lay), default=None)
    if d <= 14:
        return (0.3, f"back in {d} days off a good race") if f["last_itm"] else None
    if 46 <= d <= 90:
        if best is not None and best >= 15:
            return 0.5, f"{d} days, trainer layoff stat {best}%"
        return None
    if 91 <= d <= 180:
        if f["num_works"] >= 3 and f["has_work_5f_or_more"]:
            return 0.0, f"{d} days but well drilled"
        return -0.3, f"{d} days off"
    if d > 180:
        if best is not None and best >= 18 and f["num_works"] >= 4:
            return -0.3, f"{d} days off, trainer {best}% off layoffs"
        return -1.0, f"{d} days off"
    return None


@rule("F7", "Second / third start off the layoff", "form", 2)
def f7(f, ctx):
    """Second start after a 60+ day layoff: +1.0 (classic improvement spot) if the comeback race was within
    6 lengths; third start: +0.5."""
    n = f["races_since_layoff"]
    if n == 1 and f["last_beaten"] is not None and f["last_beaten"] <= 6:
        return 1.0, "2nd off the layoff"
    if n == 2:
        return 0.5, "3rd off the layoff"
    return None


@rule("F8", "Consistency", "form", 3)
def f8(f, ctx):
    """Career ITM% >= 60 with 4+ starts: 1.0; >= 45: 0.5; <= 20% with 8+ starts: -0.7."""
    if not f["starts"] or f["starts"] < 4:
        return None
    if f["itm_pct"] >= 60:
        return 1.0, f"ITM {f['itm_pct']}% ({f['starts']} starts)"
    if f["itm_pct"] >= 45:
        return 0.5, f"ITM {f['itm_pct']}%"
    if f["starts"] >= 8 and f["itm_pct"] <= 20:
        return -0.7, f"ITM only {f['itm_pct']}%"
    return None


@rule("F9", "Recent workout pattern", "form", 2)
def f9(f, ctx):
    """A bullet work (fastest of the day) among the last 4 works: +0.7; two or more top-15% works: +0.5;
    no workout since a layoff of 45+ days: -0.5."""
    pts, notes = 0.0, []
    if any(w.get("bullet") for w in (f.get("_works") or [])[:4]):
        pts += 0.7
        notes.append("bullet work")
    if f["recent_fast_works"] >= 2:
        pts += 0.5
        notes.append(f"{f['recent_fast_works']} sharp works")
    if f["days_since"] is not None and f["days_since"] >= 45 and f["works_since_last"] == 0 and not f["first_time_starter"]:
        pts -= 0.5
        notes.append("no works since last race")
    return (pts, ", ".join(notes)) if pts else None


@rule("F10", "Two straight in-the-money finishes", "form", 1.5)
def f10(f, ctx):
    """ITM in each of the last two starts: 1.0; last three: 1.5."""
    if f["itm_streak"] >= 3:
        return 1.5, "ITM last 3"
    if f["itm_streak"] >= 2:
        return 1.0, "ITM last 2"
    return None


# =========================================================================
# K — CONNECTIONS
# =========================================================================
@rule("K1", "Trainer win percentage (year)", "connections", 3)
def k1(f, ctx):
    """Trainer's current-year win%: >= 22: 1.0; 17-21: 0.6; 12-16: 0.2; <= 7 (with 30+ starts): -0.8."""
    t = f["trainer_year"]
    if not t:
        return None
    w = t["win_pct"]
    if w >= 22:
        return 1.0, f"trainer {w}% ({t['starts']} sts)"
    if w >= 17:
        return 0.6, f"trainer {w}%"
    if w >= 12:
        return 0.2, f"trainer {w}%"
    if w <= 7 and t["starts"] >= 30:
        return -0.8, f"trainer only {w}%"
    return None


@rule("K2", "Trainer angle stats", "connections", 3)
def k2(f, ctx):
    """Brisnet trainer category stats that apply today (e.g. '2nd off layoff', 'Turf to Dirt', '1stTimeBlinkers'):
    any category with 15+ starts and win% >= 20 or ROI >= +0.20: +0.6 each (max 1.2); any with 15+ starts
    and win% <= 7: -0.5 each (max -1.0). A '+' flag from Brisnet adds 0.2."""
    pts, notes = 0.0, []
    for t in f["trainer_angles"]:
        if t["starts"] < 15:
            continue
        if t["win_pct"] >= 20 or t["roi"] >= 0.20:
            pts += 0.6 + (0.2 if t.get("flag") else 0)
            notes.append(f"{t['category']} {t['win_pct']}% ROI {t['roi']:+.2f}")
        elif t["win_pct"] <= 7:
            pts -= 0.5
            notes.append(f"{t['category']} only {t['win_pct']}%")
    pts = max(-1.0, min(1.2, pts))
    return (pts, "; ".join(notes)) if pts else None


@rule("K3", "Jockey win percentage", "connections", 2)
def k3(f, ctx):
    """Jockey current-year win%: >= 18: 1.0; 13-17: 0.5; <= 6 with 50+ mounts: -0.7."""
    j = f["jockey_year"]
    if not j:
        return None
    w = j["win_pct"]
    if w >= 18:
        return 1.0, f"jockey {w}%"
    if w >= 13:
        return 0.5, f"jockey {w}%"
    if w <= 6 and j["starts"] >= 50:
        return -0.7, f"jockey only {w}%"
    return None


@rule("K4", "Jockey/trainer combination", "connections", 2)
def k4(f, ctx):
    """Jockey-with-this-trainer (last 60 days) stat: 5+ starts and win% >= 25: 1.0; 5+ starts and 0%: -0.5."""
    c = f["jt_combo"]
    if not c or c["starts"] < 5:
        return None
    if c["win_pct"] >= 25:
        return 1.0, f"jky/trn combo {c['win_pct']}% of {c['starts']}"
    if c["win_pct"] == 0:
        return -0.5, f"jky/trn combo 0 for {c['starts']}"
    return None


@rule("K5", "Hot trainer", "connections", 2)
def k5(f, ctx):
    """Brisnet 'Hot Trainer in last 14 days' comment present: 1.0."""
    for s in f["positives"]:
        if "Hot Trainer" in s:
            return 1.0, s
    return None


@rule("K7", "Trainer meet form", "connections", 1.5)
def k7(f, ctx):
    """Trainer's record at the current meet: 8+ starts and win% >= 25: +1.0; 15+ starts and 0 wins: -0.6."""
    m = f["trainer_meet"]
    if not m or m.get("starts", 0) < 8:
        return None
    if m["win_pct"] >= 25:
        return 1.0, f"trainer {m['win']} for {m['starts']} at meet"
    if m["starts"] >= 15 and m["win"] == 0:
        return -0.6, f"trainer 0 for {m['starts']} at meet"
    return None


@rule("K6", "Rider upgrade", "connections", 1.5)
def k6(f, ctx):
    """Jockey change to a rider winning >= 15% on the year, after a rider who was not listed: 1.0."""
    j = f["jockey_year"]
    if f["jockey_switch"] and j and j["win_pct"] >= 15:
        return 1.0, f"switches to {j['win_pct']}% rider"
    return None


# =========================================================================
# D — DISTANCE / SURFACE
# =========================================================================
@rule("D1", "Record at today's distance", "distance", 3)
def d1(f, ctx):
    """Starts at today's distance: a win: 1.0; ITM (no win) in 2+ tries: 0.5; 0-for-4+ with no ITM: -0.6."""
    if f["dist_starts"] == 0:
        return None
    if f["dist_wins"] >= 1:
        return 1.0, f"{f['dist_wins']} win(s) at distance"
    if f["dist_itm"] >= 2:
        return 0.5, f"ITM {f['dist_itm']} of {f['dist_starts']} at distance"
    if f["dist_starts"] >= 4 and f["dist_itm"] == 0:
        return -0.6, f"0 for {f['dist_starts']} at distance"
    return None


@rule("D2", "Record on today's surface", "distance", 3)
def d2(f, ctx):
    """Starts on today's surface (dirt-fast or turf): win% >= 25 with 3+ starts: 1.0; ITM% >= 50: 0.5;
    0 for 6+ with ITM% < 20: -0.7."""
    n = f["surface_starts"]
    if n < 3:
        return None
    if f["surface_wins"] / n >= 0.25:
        return 1.0, f"{f['surface_wins']} of {n} on surface"
    if f["surface_itm"] / n >= 0.5:
        return 0.5, f"ITM {f['surface_itm']} of {n} on surface"
    if n >= 6 and f["surface_itm"] / n < 0.2:
        return -0.7, f"ITM only {f['surface_itm']} of {n} on surface"
    return None


@rule("D3", "Surface switch with no experience", "distance", 3)
def d3(f, ctx):
    """Horse has never run on today's surface: judged by Brisnet pedigree rating for that surface
    (>= 110: +0.5; 100-109: 0; < 100: -0.7) and, turf-to-dirt, by the trainer's 'Turf to Dirt' stat
    (win% >= 20: +0.5)."""
    if f["surface_starts"] > 0 or f["first_time_starter"]:
        return None
    pts, notes = 0.0, []
    pr = f["ped_surface_rating"]
    if pr is not None:
        if pr >= 110:
            pts += 0.5
        elif pr < 100:
            pts -= 0.7
        notes.append(f"pedigree surface rating {pr}")
    for t in f["trainer_angles"]:
        if re.search(r"Turf to Dirt|Dirt to Turf|1st.*Turf", t["category"]) and t["starts"] >= 10 and t["win_pct"] >= 20:
            pts += 0.5
            notes.append(f"{t['category']} {t['win_pct']}%")
    if not notes:
        return -0.3, "no starts on this surface"
    return pts, "first on surface; " + ", ".join(notes)


@rule("D4", "Distance change suitability", "distance", 2.5)
def d4(f, ctx):
    """Stretching out sprint-to-route: +0.6 if late pace (LP) avg >= par-late and sire AWD >= 7.0; -0.6 if the horse
    has faded (negative last-race 2c pace figure change) and sire AWD < 6.5.  Route-to-sprint: +0.5 if best E2 is
    within 3 of the field's best; -0.5 otherwise."""
    race = ctx["race"]
    if f["sprint_to_route"] and f["dist_starts"] == 0:
        good = (f["avg_lp"] is not None and ctx["par_late"] and f["avg_lp"] >= ctx["par_late"]) and (f["sire_awd"] or 0) >= 7.0
        bad = (f["sire_awd"] or 9) < 6.5 and f["last_bad_effort"]
        if good:
            return 0.6, f"stretches out: LP {f['avg_lp']} vs par {ctx['par_late']}, sire AWD {f['sire_awd']}"
        if bad:
            return -0.6, f"stretches out: sire AWD {f['sire_awd']}, faded last"
        return None
    if f["route_to_sprint"] and f["dist_starts"] == 0:
        if f["best_e2"] is not None and ctx["top_best_e2"] is not None and f["best_e2"] >= ctx["top_best_e2"] - 3:
            return 0.5, f"cuts back with E2 {f['best_e2']}"
        return -0.5, "cuts back without early pace"
    return None


@rule("D5", "Track record (today's track)", "distance", 1.5)
def d5(f, ctx):
    """Won at today's track: 1.0; ITM 2+ times here: 0.5."""
    if f["track_wins"] >= 1:
        return 1.0, f"{f['track_wins']} win(s) at track"
    if f["track_itm"] >= 2:
        return 0.5, f"ITM {f['track_itm']} times at track"
    return None


@rule("D6", "Turf pedigree / proven turf speed (turf races only)", "distance", 2)
def d6(f, ctx):
    """Turf race: best turf figure ranks 1st: +1.0; horse with 0 turf starts and pedigree turf rating < 100: -0.8."""
    if ctx["race"]["surface"] != "turf":
        return None
    if ctx["rank_best_surface_speed"].get(f["pgm"]) == 1 and f["surface_starts"] > 0:
        return 1.0, f"best turf figure {f['best_surface_speed']}"
    if f["surface_starts"] == 0 and not f["first_time_starter"] and (f["ped_surface_rating"] or 100) < 100:
        return -0.8, f"no turf starts, turf pedigree {f['ped_surface_rating']}"
    return None


# =========================================================================
# A — AGE / WEIGHT
# =========================================================================
@rule("A1", "Weight / age concession", "age_weight", 1)
def a1(f, ctx):
    """Carries 4+ lbs less than the heaviest weight in the field: +0.5; 3yo against older after September (gets the
    scale-of-weights allowance and is still maturing): +0.3."""
    pts, notes = 0.0, []
    w = f["weight"]
    if w is not None and ctx.get("max_weight") and ctx["max_weight"] - w >= 4:
        pts += 0.5
        notes.append(f"carries {w} vs top weight {ctx['max_weight']}")
    if f["age"] == 3 and ctx.get("has_older") and ctx["race"].get("date_month", 11) >= 9:
        pts += 0.3
        notes.append("3yo vs older")
    return (pts, ", ".join(notes)) if pts else None


# =========================================================================
# E — EQUIPMENT / MEDICATION
# =========================================================================
@rule("E1", "First-time blinkers", "equipment", 2)
def e1(f, ctx):
    """Blinkers added today: trainer '1stTimeBlinkers' win% >= 15 (10+ starts): +1.0; <= 7: -0.6; otherwise +0.2."""
    if not f["blinkers_on"]:
        return None
    for t in f["trainer_angles"]:
        if "Blinker" in t["category"] and t["starts"] >= 10:
            if t["win_pct"] >= 15:
                return 1.0, f"blinkers on, trainer {t['win_pct']}% with 1st-time blinkers"
            if t["win_pct"] <= 7:
                return -0.6, f"blinkers on, trainer only {t['win_pct']}% with 1st-time blinkers"
    return 0.2, "blinkers on"


@rule("E2", "Blinkers off", "equipment", 1)
def e2(f, ctx):
    """Blinkers removed today (often a horse that was too keen): +0.3 for P/S types, 0 otherwise."""
    if f["blinkers_off"] and f["closer_type"]:
        return 0.3, "blinkers off"
    return None


@rule("E3", "First-time Lasix", "equipment", 1)
def e3(f, ctx):
    """First-time Lasix (typically a foreign import or a 2yo): +0.5."""
    if f["first_lasix"]:
        return 0.5, "first-time Lasix"
    return None


# =========================================================================
# Q — BRISNET QUICKPLAY COMMENTS
# =========================================================================
STRONG_POS = ["Highest last race speed rating", "fastest among today's starters", "Drops in class",
              "Hot Trainer", "Ran well", "Won last", "Up in class", "May improve while returning", "Highest Prime Power"]
STRONG_NEG = ["Poor Speed Figures", "Always far back", "Beaten by weaker", "Poor trainer win%", "Poor jockey win%",
              "Has never raced", "Moves up in class", "Speed Figs rank poorly", "Has not raced for more than 6", "Has not raced for more than 1 year"]


@rule("Q1", "QuickPlay positive comments", "comments", 1.2)
def q1(f, ctx):
    """Each Brisnet positive (ñ) comment: +0.5; strong ones (speed rating best in field, class drop, hot trainer...): +1.0. Max 3.0."""
    pts, notes = 0.0, []
    for s in f["positives"]:
        pts += 1.0 if any(k.lower() in s.lower() for k in STRONG_POS) else 0.5
        notes.append(s)
    pts = min(pts, 3.0)
    return (pts, "; ".join(notes)) if pts else None


@rule("Q2", "QuickPlay negative comments", "comments", 1.2)
def q2(f, ctx):
    """Each Brisnet negative (×) comment: -0.5; strong ones (poor figures, always far back, beaten by weaker, poor trainer...): -1.0.
    Min -3.0.  The generic 'Has not raced for more than 2 months' counts only -0.25 (layoffs are handled by F6)."""
    pts, notes = 0.0, []
    for s in f["negatives"]:
        if re.search(r"more than [23] months", s):
            pts -= 0.25
        else:
            pts -= 1.0 if any(k.lower() in s.lower() for k in STRONG_NEG) else 0.5
        notes.append(s)
    pts = max(pts, -3.0)
    return (pts, "; ".join(notes)) if pts else None


# =========================================================================
# M — MAIDENS & FIRST-TIME STARTERS
# =========================================================================
@rule("M1", "First-time starter profile", "maiden", 4)
def m1(f, ctx):
    """Debut runner: trainer '1st time starter' stat win% >= 15 (+0.6), sire 1st-time-starter win% >= 14 (+0.4),
    bullet or top-10% work in last 4 (+0.4), 4+ published works (+0.2); debuting in a maiden-claiming race (-0.5);
    fewer than 3 works (-0.5)."""
    if not f["first_time_starter"]:
        return None
    pts, notes = 0.0, []
    for t in f["trainer_angles"]:
        if re.search(r"1st|First|Debut", t["category"]) and re.search(r"[Ss]tarter|Strtr|Debut|1stStart", t["category"]) and t["starts"] >= 10:
            if t["win_pct"] >= 15:
                pts += 0.6
                notes.append(f"{t['category']} {t['win_pct']}%")
            elif t["win_pct"] <= 6:
                pts -= 0.5
                notes.append(f"{t['category']} only {t['win_pct']}%")
    if (f["sire_first_pct"] or 0) >= 14:
        pts += 0.4
        notes.append(f"sire {f['sire_first_pct']}% 1st-timers")
    if f["bullet_works"] or f["recent_fast_works"]:
        pts += 0.4
        notes.append("sharp works")
    if f["num_works"] >= 4:
        pts += 0.2
    elif f["num_works"] < 3:
        pts -= 0.5
        notes.append("light work tab")
    if ctx["race"]["class_code"] == "MCL":
        pts -= 0.5
        notes.append("debuts in maiden claimer")
    return pts, "first-timer: " + ", ".join(notes)


@rule("M2", "Maiden-special-weight dropper into maiden claiming", "maiden", 5)
def m2(f, ctx):
    """Today is a maiden-claiming race and the horse's last 1-2 starts were in maiden special weight / higher-priced
    maiden claimers with a speed figure within 4 of today's par: +1.0 (the classic MSW-to-MCL drop)."""
    if ctx["race"]["class_code"] != "MCL" or not f["last"]:
        return None
    last = f["last"]
    par = ctx["par_speed"]
    if last["class_code"] in ("MSW", "MOC") or (last["class_code"] == "MCL" and (last.get("race_purse_or_price") or 0) >= 2 * (ctx["race"].get("claiming_price") or 1)):
        if par and f["best_last3"] is not None and f["best_last3"] >= par - 4:
            return 1.0, f"drops from {last['race_type']} with figure {f['best_last3']} vs par {par}"
        return 0.4, f"drops from {last['race_type']}"
    return None


@rule("M3", "Chronic maiden", "maiden", 3)
def m3(f, ctx):
    """Maiden with 8+ starts: -0.8; 12+ starts: -1.2.  Maiden with 3+ seconds and no win ('sucker horse'): additional -0.4."""
    if not f["is_maiden"] or f["first_time_starter"]:
        return None
    pts, notes = 0.0, []
    if f["starts"] >= 12:
        pts -= 1.2
        notes.append(f"0 for {f['starts']}")
    elif f["starts"] >= 8:
        pts -= 0.8
        notes.append(f"0 for {f['starts']}")
    if f["places"] >= 3:
        pts -= 0.4
        notes.append(f"{f['places']} seconds")
    return (pts, ", ".join(notes)) if pts else None


@rule("M4", "Lightly raced improver", "maiden", 2)
def m4(f, ctx):
    """Horse with 1-3 career starts whose last figure improved 5+ points on its previous start: +1.0;
    second career start after a debut within 4 lengths: +0.6."""
    if f["first_time_starter"] or f["starts"] > 3:
        return None
    s = f["speed_last3"]
    if len(s) >= 2 and s[0] >= s[1] + 5:
        return 1.0, f"improved {s[1]}->{s[0]}"
    if f["starts"] == 1 and f["last_beaten"] is not None and f["last_beaten"] <= 4:
        return 0.6, f"2nd start, debut beaten {f['last_beaten']}L"
    return None


# =========================================================================
# X — ELIMINATIONS (hard filters; factor -1 marks the horse as a throw-out)
# =========================================================================
@rule("X1", "Hopelessly slow", "elimination", 1, hard=True)
def x1(f, ctx):
    """Throw-out: best speed figure of the last three starts is 10+ points below today's par AND the horse has
    3+ starts AND it is not dropping 3+ class levels."""
    par = ctx["par_speed"]
    if par and f["best_last3"] is not None and f["starts"] >= 3 and f["best_last3"] <= par - 10:
        if f["class_move"] is not None and f["class_move"] <= -3:
            return None
        return -1.0, f"best of last 3 {f['best_last3']} is {par - f['best_last3']} below par {par}"
    return None


@rule("X2", "Long layoff, no foundation", "elimination", 1, hard=True)
def x2(f, ctx):
    """Throw-out: 365+ days since last race with fewer than 4 workouts."""
    if f["days_since"] is not None and f["days_since"] >= 365 and f["num_works"] < 4:
        return -1.0, f"{f['days_since']} days off, {f['num_works']} works"
    return None


@rule("X3", "Also-eligible / main-track-only", "elimination", 1, hard=True)
def x3(f, ctx):
    """Flag (not a throw-out): horse is on the also-eligible list or main-track-only; it runs only if scratches occur.
    Scored normally but reported with an AE/MTO flag."""
    if f["entry_status"]:
        return 0.0, f"{f['entry_status']} - needs a scratch to run"
    return None


@rule("X4", "Badly outclassed", "elimination", 1, hard=True)
def x4(f, ctx):
    """Throw-out: average class rating of the last three starts is 8+ points below the field's best AND
    the horse is not dropping in class."""
    top = ctx["top_avg_class_rating"]
    if top and f["avg_class_rating"] is not None and top - f["avg_class_rating"] >= 8:
        if f["class_move"] is not None and f["class_move"] < 0:
            return None
        return -1.0, f"avg class rating {f['avg_class_rating']} vs field best {top}"
    return None


# =========================================================================
# V — VALUE (odds overlay)
# =========================================================================
@rule("V1", "Morning-line value", "value", 3)
def v1(f, ctx):
    """Applied after scoring (see engine): compares the horse's score-implied win probability with the
    morning-line implied probability.  Overlay (fair odds < ML by 30%+): +1.0; underlay (ML < 60% of fair): -0.8.
    Chalk at 6/5 or lower never gets a value bonus."""
    return None   # evaluated by the engine with knowledge of the whole field
