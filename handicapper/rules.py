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
Multi-race (Pick 3 / Pick 4) construction rules (H*) live in multirace.py.

Expert basis
------------
Every docstring ends with a "Basis:" sentence naming the published practice the
rule encodes, so a reviewer can judge the rule against its source rather than
against the author's taste.  Sources referred to by short name:

  Beyer      A. Beyer, *Picking Winners* / *Beyer on Speed* (figures, pairing, bounce, trips)
  Brohamer   T. Brohamer, *Modern Pace Handicapping* (E1/E2/LP matchups, pace line)
  Quirin     W. Quirin, *Winning at the Races* (first-call leader wins ~26%, speed points, impact values)
  Davidowitz S. Davidowitz, *Betting Thoroughbreds* (class drops, beaten favourites, trainer intent)
  Quinn      J. Quinn, *The Handicapper's Condition Book* (eligibility conditions, class ladders)
  Litfin     D. Litfin, *Expert Handicapping* (form cycles, freshening, second-time starters)
  Meadow     B. Meadow, *Money Secrets at the Racetrack* (odds lines, overlays)
  Brisnet    Brisnet Ultimate PP / Prime Power / Run-style FAQs (definitions and their own hit-rate studies)
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
    """Highest Brisnet speed figure in the field last time out: full credit; within 2 points of the top: half.
    Basis: Beyer - the last-race figure is the single most predictive number on the page when it is not a fluke."""
    if f["last_speed"] is None or ctx["top_last_speed"] is None:
        return None
    if f["last_speed"] == ctx["top_last_speed"]:
        return 1.0, f"last speed {f['last_speed']} is top in field"
    if f["last_speed"] >= ctx["top_last_speed"] - 2:
        return 0.5, f"last speed {f['last_speed']} within 2 of top ({ctx['top_last_speed']})"
    return None


@rule("S2", "Best of last three speed figures", "speed", 6)
def s2(f, ctx):
    """Best Brisnet speed figure among the last three starts ranks 1st (1.0), 2nd (0.6) or 3rd (0.3) in the field.
    Basis: Beyer - judge a horse on the best of its recent figures, not only the last one."""
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
    >= par +3: 1.0; >= par: 0.5; par-4 .. par-1: 0; below par-4: -0.6; below par-8: -1.0.
    Basis: Beyer / Brisnet par method - a horse that has not run to today's par is unlikely to do so today."""
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
    A horse with no matching race gets no credit here (handled by D-rules).
    Basis: Beyer - compare figures earned under like conditions; a dirt-sprint figure says little about a turf route."""
    r = ctx["rank_best_match_speed"].get(f["pgm"])
    if r == 1:
        return 1.0, f"best matching-conditions figure {f['best_match_speed']} ranks 1st"
    if r == 2:
        return 0.5, f"best matching-conditions figure {f['best_match_speed']} ranks 2nd"
    return None


@rule("S5", "Improving / declining figure pattern", "speed", 3)
def s5(f, ctx):
    """Three consecutively rising speed figures: +1.0 (horse is on an upward form cycle).
    Three consecutively falling figures: -1.0 (tailing off).
    Basis: Litfin form cycles - improving patterns continue more often than they reverse; declining ones rarely snap back."""
    if f["improving"]:
        return 1.0, f"figures rising {f['speed_last3'][::-1]}"
    if f["declining"]:
        return -1.0, f"figures falling {f['speed_last3'][::-1]}"
    return None


@rule("S6", "Bounce risk after a career-top figure", "speed", 4)
def s6(f, ctx):
    """Last race was a new career top by 5+ points over every previous figure AND the horse has 3+ starts:
    -1.0; -1.3 if it comes back within 21 days; a further -0.3 if the jump was 10+ points.  The penalty is sized so
    that it offsets most, not all, of the credit S1/S2/S4 give the same figure: the horse stays a contender but is
    no longer a single (H2 lists S6 among the vulnerability rules).
    Basis: Beyer / Ragozin "bounce" - a lifetime top run with effort is usually followed by a regression, more so
    off a short rest and the bigger the leap."""
    if f["career_top_last"] and f["starts"] >= 3:
        short = f["days_since"] is not None and f["days_since"] < 21
        jump = f["last_speed"] - f["prev_best"]
        fac = -1.3 if short else -1.0
        if jump >= 10:
            fac -= 0.3
        return fac, f"career top {f['last_speed']} vs prior best {f['prev_best']} (+{jump})" + (" on short rest" if short else "")
    return None


@rule("S7", "Prime Power rank", "speed", 4)
def s7(f, ctx):
    """Brisnet Prime Power rank in the field: 1st 1.0, 2nd 0.6, 3rd 0.35. Bonus +0.4 if the top-ranked horse
    is 4+ points clear of the second.  Weight is deliberately moderate: Prime Power is itself a composite of speed,
    class, pace and form, so a high weight double-counts the S/C/P/F rules.
    Basis: Brisnet's own studies - top Prime Power wins ~31-39% overall (more when clear by 3+ points); experts use it
    as a contender screen, not as the selection."""
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


@rule("S8", "Paired figures near par", "speed", 3)
def s8(f, ctx):
    """All of the last three speed figures are within 3 points of today's par or better: 1.0 (reliable, no bounce risk).
    Or the last two figures are "paired" (within 2 points of each other) and both at least par-3: 0.8.
    Basis: Beyer - a horse that pairs two figures has shown that level is its true form, so the figure can be trusted."""
    par = ctx["par_speed"]
    s = f["speed_last3"]
    if par and len(s) == 3 and all(v >= par - 3 for v in s):
        return 1.0, f"last 3 figures {s[::-1]} all >= par-3 ({par - 3})"
    if par and f["paired_figs"] and all(v >= par - 3 for v in s[:2]):
        return 0.8, f"paired figures {s[1]}/{s[0]} at par-3 or better"
    return None


@rule("S9", "Figure standout", "speed", 4)
def s9(f, ctx):
    """The horse's best figure of its last two starts beats every rival's best-of-last-three by 2+ points: 1.0;
    by exactly 1: 0.5.  Not awarded if that figure was a 5+ point career top (S6 already flags bounce risk).
    Basis: Beyer's "figure horse" - when one horse has run faster than anything the others have ever run recently,
    the figures alone make it the most likely winner."""
    mine = f["best_two_recent"]
    if mine is None or f["career_top_last"]:
        return None
    others = [v for pgm, v in ctx["best_last3_by_pgm"].items() if pgm != f["pgm"] and v is not None]
    if not others:
        return None
    edge = mine - max(others)
    if edge >= 2:
        return 1.0, f"best recent {mine} beats field best {max(others)} by {edge}"
    if edge >= 1:
        return 0.5, f"best recent {mine} beats field best {max(others)} by {edge}"
    return None


@rule("S10", "Off-surface last race excused", "speed", 2)
def s10(f, ctx):
    """The last race was on a different surface from today's, the horse has two or more earlier starts on today's
    surface, and the off-surface figure is below its best recent same-surface figure: the speed rules (S1-S9, X1)
    read its most recent same-surface figures instead of the off-surface line, F5 does not count the off-surface
    flop, and this rule adds +0.5 when the best same-surface figure is within 2 of today's par (returning to a
    surface it handles), +0.2 otherwise.  A single same-surface line is not enough evidence to switch, and a good
    race on the wrong surface is not excused - it still counts as form.
    Basis: Beyer / Quinn - a figure earned on the wrong surface says little about today; judge the horse on the
    races run under today's conditions.  Brisnet prints the same idea as "May improve while returning to Turf"."""
    if not f["use_surface_figs"]:
        return None
    par = ctx["par_speed"]
    last = f["last"]
    where = (last or {}).get("surface", "?")
    good = par is not None and f["best_last3"] is not None and f["best_last3"] >= par - 2
    return (0.5 if good else 0.2), (f"last race on {where} ({f['off_surface_speed']}) excused; "
                                    f"{ctx['race']['surface']} figures {f['speed_last3'][::-1]} used")


@rule("D7", "Best figure at the exact distance", "distance", 2)
def d7(f, ctx):
    """Brisnet 'best speed at distance' (Dis record) ranks 1st in the field: 1.0; 2nd: 0.5.
    Basis: Quinn / "horses for courses" - proven ability at the exact trip is a secondary but real edge."""
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
    3+ levels 1.0.  Discounted to 0.3 ("dropping for a reason") if the horse was beaten 10+ lengths last time, or if
    its figures have declined three straight and it was out of the money each time.
    Basis: Davidowitz - the class drop is the strongest angle on the page when the horse shows some sign of form, and
    a trap when the barn is dropping a horse that is going the wrong way."""
    m = f["class_move"]
    if m is None or m >= -0.5:
        return None
    fac = 1.0 if m <= -3 else 0.6
    why = ""
    if f["last_beaten"] is not None and f["last_beaten"] >= 10:
        fac, why = 0.3, " (badly beaten last)"
    elif f["declining"] and f["itm_streak"] == 0 and f["num_clean_pp"] >= 3 and all(p["finish_pos"] > 3 for p in f["_pp3"]):
        fac, why = 0.3, " (declining, dropping for a reason)"
    return fac, f"drops {abs(m):.1f} class levels" + why


@rule("C2", "Class rise", "class", 4)
def c2(f, ctx):
    """Today's class level is above the last race's: -0.6 for a 1-3 level rise, -1.0 for 3+.
    Waived (0) if the horse won last time by 2+ lengths or earned a figure above par.
    Basis: Quinn / Davidowitz - most horses moving up lose, except those whose last race (margin or figure) says the
    new level is within reach."""
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
    """Average Brisnet class rating of the last three starts ranks 1st (1.0), 2nd (0.5) or 3rd (0.25).
    Basis: Brisnet class ratings measure the quality of fields actually faced; the horse that has been meeting the
    best company has the most "hidden class"."""
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
    """Competitive (finished within 3 lengths) in a race whose class level was >= today's within the last 3 starts: 1.0.
    Basis: Quinn - "proven at the level" is the cleanest class credential; recent is what counts."""
    last3 = [p for p in f.get("_pp3", [])]
    for p in last3:
        lvl = p.get("_level")
        if lvl is not None and f["today_level"] is not None and lvl >= f["today_level"] and p.get("beaten_lengths") is not None and p["beaten_lengths"] <= 3:
            return 1.0, f"within 3L at {p['race_type']} on {p['date']}"
    return None


@rule("C5", "Last race rating beats the field", "class", 3)
def c5(f, ctx):
    """Brisnet race rating of the last race (strength of the field it faced) ranks 1st: 1.0, 2nd: 0.5.
    Basis: Davidowitz "key race" thinking - a horse coming out of the strongest recent field is better than its finish."""
    r = ctx["rank_race_rating_last"].get(f["pgm"])
    if r == 1:
        return 1.0, f"last race rating {f['race_rating_last']} ranks 1st"
    if r == 2:
        return 0.5, f"last race rating {f['race_rating_last']} ranks 2nd"
    return None


@rule("C6", "Claimed last out: the new barn's intent", "class", 2)
def c6(f, ctx):
    """Horse was claimed last time.  Dropped below the price it was claimed for: -0.8 (the new barn found a problem),
    softened to +0.3 when the trainer wins >= 20% (sharp claiming barns drop to cash quickly).  Raised in class off the
    claim with a trainer winning >= 15%: +0.8 (the barn thinks it stole a horse).  Same level: 0.
    Basis: Davidowitz - a claimed horse dropped below its purchase price is a red flag unless the trainer is a known
    manipulator; a claimed horse moved up by a strong barn is one of the most reliable positive intent signals."""
    if not f["last_claimed"]:
        return None
    ty = f["trainer_year"] or {}
    tw = ty.get("win_pct", 0)
    price, today = f["last_claim_price"], f["today_claiming_price"]
    if price and today and today < price:
        if tw >= 20:
            return 0.3, f"claimed for {price}, dropped to {today} by a {tw}% barn"
        return -0.8, f"claimed for {price}, now in for {today}"
    if f["class_move"] is not None and f["class_move"] > 0.5 and tw >= 15:
        return 0.8, f"raised in class off the claim by a {tw}% barn"
    return None


@rule("C7", "First time for a tag", "class", 3)
def c7(f, ctx):
    """Today is the horse's first claiming race after 2+ starts in maiden-special-weight, allowance, optional-claiming
    or stakes company: +1.0 if its best figure of the last three is within 2 of today's par, otherwise +0.4.
    Basis: Quinn / Davidowitz - the move from non-claiming to claiming company is the most reliable class drop on the
    page, because the horse has been facing horses that could not be bought."""
    if not f["first_time_for_tag"]:
        return None
    par = ctx["par_speed"]
    if par and f["best_last3"] is not None and f["best_last3"] >= par - 2:
        return 1.0, f"first time in for a tag with figure {f['best_last3']} vs par {par}"
    return 0.4, "first time in for a tag"


@rule("C8", "Back class", "class", 2)
def c8(f, ctx):
    """Horse has finished within 2 lengths at a class level 2+ rungs above today's within its last 10 starts, but not in
    its last three: +0.7 if it has been freshened (45+ days) or the trainer wins >= 15%; otherwise +0.3.
    Basis: Davidowitz "back class" - horses dropping to a level far below their proven ability often rebound at a
    price, especially after a rest or in the hands of a capable barn."""
    if not f["back_class"]:
        return None
    tw = (f["trainer_year"] or {}).get("win_pct", 0)
    strong = (f["days_since"] is not None and f["days_since"] >= 45) or tw >= 15
    return (0.7 if strong else 0.3), f"competitive at level {f['best_competitive_level']:.1f} vs today's {f['today_level']:.1f}"


@rule("C9", "Maiden graduate moving into winners' company", "class", 3)
def c9(f, ctx):
    """Last race was a maiden win.  Into an allowance / optional-claiming n1x race or open claiming company: -0.7 if
    the win came in a maiden claimer, -0.4 if in maiden special weight; waived when the winning figure met today's par.
    Into a claiming race written for non-winners of two (n2L): 0 (the race is written for exactly this horse).
    Basis: Quinn's condition book - the jump from maidens to winners is the biggest in racing; Davidowitz - a
    maiden-claiming graduate in open company is "among the worst bets in racing"."""
    if not f["last_maiden_win"]:
        return None
    if f["today_n2l"]:
        return None
    rc = ctx["race"]["class_code"]
    if rc not in ("ALW", "OC", "CLM", "STR", "STK", "HCP"):
        return None
    par = ctx["par_speed"]
    if par and f["last_speed"] is not None and f["last_speed"] >= par:
        return 0.0, f"maiden graduate but won with {f['last_speed']} vs par {par}"
    if f["last_maiden_win_claiming"]:
        return -0.7, "maiden-claiming graduate facing winners"
    return -0.4, "maiden graduate facing winners"


@rule("C10", "Drop in class after a win", "class", 3)
def c10(f, ctx):
    """Won last time and drops 2+ class levels today: -0.6 (a sound winner is not dropped; something is wrong), unless
    the trainer wins >= 20% or shows a Brisnet "Drops off win" stat of 15%+ with 10+ starts (then +0.3, a barn that
    cashes this way on purpose).
    Basis: Davidowitz - the suspicious drop; Brisnet trainer-category stats identify the barns that do it successfully."""
    if not f["last_won"] or f["class_move"] is None or f["class_move"] > -2:
        return None
    tw = (f["trainer_year"] or {}).get("win_pct", 0)
    stat = next((t for t in f["trainer_angles"] if re.search(r"[Dd]rops? off win|[Dd]own 2", t["category"]) and t["starts"] >= 10), None)
    if tw >= 20 or (stat and stat["win_pct"] >= 15):
        return 0.3, f"drops {abs(f['class_move']):.1f} levels off a win for a barn that does it (" + (f"{stat['category']} {stat['win_pct']}%" if stat else f"{tw}%") + ")"
    return -0.6, f"drops {abs(f['class_move']):.1f} levels after winning"


# =========================================================================
# P — PACE
# =========================================================================
@rule("P1", "Lone early speed", "pace", 7)
def p1(f, ctx):
    """Only one horse in the field has early-speed points >= 5 and is at least 2 points clear of all others,
    with no other 'E' type: that horse gets 1.0 (uncontested lead).  Full credit on dirt, 0.7 on turf.
    Basis: Quirin - the first-call leader wins ~26% of all races and far more when unpressed; lone speed is the
    most powerful single pace angle, weaker on turf where closers fare better."""
    if ctx["lone_speed"] == f["pgm"]:
        return (1.0 if ctx["race"]["surface"] == "dirt" else 0.7), f"lone speed ({f['run_style']} {f['speed_pts']} pts)"
    return None


@rule("P2", "Speed duel penalty / closer bonus", "pace", 4)
def p2(f, ctx):
    """Hot pace shape (3+ 'E' types or 3+ horses with 6+ speed points): E types -1.0, E/P -0.5, P +0.5, S +1.0.
    Soft pace shape (<= 2 early types, no lone speed): E/E-P +0.4, S -0.4.
    Basis: Brohamer / Quirin - duelling speed horses beat each other; a soft pace strands deep closers."""
    shape = ctx["pace_shape"]
    rs = f["run_style"]
    if shape == "hot":
        return {"E": -1.0, "E/P": -0.5, "P": 0.5, "S": 1.0}.get(rs, 0.0) or None, f"hot pace ({ctx['num_E']} E, {ctx['num_high_pts']} high-pts) vs {rs}"
    if shape == "soft":
        return {"E": 0.4, "E/P": 0.4, "S": -0.4}.get(rs, 0.0) or None, f"soft pace vs {rs}"
    return None


@rule("P3", "Best early pace figure (E1/E2)", "pace", 4)
def p3(f, ctx):
    """Best E2 pace figure in the field: 1.0 in sprints, 0.6 in routes; best E1 adds 0.4 (sprints only).
    Basis: Brohamer - second-call (E2) pace decides sprints; who is in front at the pace call matters most."""
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
    """Best late-pace (LP) figure in the field: 1.0 in routes/turf, 0.6 in dirt sprints; 2nd best 0.4.
    Basis: Brohamer - late pace is the deciding segment in routes and on turf; in dirt sprints it is secondary."""
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
    >= 1.30: 1.0; 1.10-1.29: 0.5; <= 0.60: -1.0; 0.61-0.85: -0.5.  Weekly figures (if 5+ races) add half credit.
    Basis: Quirin impact values / Davidowitz track bias - run styles the surface is favouring win more than their share."""
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
    (meet totals). Rail horse with E/P or P style in a route adds nothing extra.
    Basis: Quirin / Brisnet track-bias stats - post-position bias is real but modest; use it only when extreme."""
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
    """Brisnet early-speed points: 7-8 points 1.0, 5-6 points 0.5 (only when the pace shape is not hot).
    Basis: Quirin speed points - horses that habitually show early speed win more than their share unless several meet."""
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
    Early type whose average E2 is 6+ below par: -0.6 (will not be able to get position).
    Basis: Brohamer - match each horse's pace figures to the par and to the projected shape of the race."""
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


@rule("P9", "Probable pace leader by E1 figure", "pace", 3)
def p9(f, ctx):
    """Among E / E/P types, the horse whose average first-call (E1) figure beats the next early type's by 3+ points:
    +1.0 (it should control the lead, whatever the speed points say).  Two or more 'E' types whose E1 averages are
    all within 1 point of the top early figure: -0.5 each (a duel is likely).
    Basis: Brohamer / Sartin pace-line matchups - compare the leaders' E1 figures directly; Quirin - duellers win
    less often than lone or pressured leaders."""
    lead = ctx["e1_leaders"]
    if not lead or not f["early_type"] or f["avg_e1"] is None:
        return None
    if lead[0]["pgm"] == f["pgm"]:
        if len(lead) == 1 or lead[0]["avg_e1"] - lead[1]["avg_e1"] >= 3:
            return 1.0, f"E1 {f['avg_e1']} is {lead[0]['avg_e1'] - (lead[1]['avg_e1'] if len(lead) > 1 else 0):.0f} clear of the next early type"
    duel = [x for x in lead if x["run_style"] == "E" and lead[0]["avg_e1"] - x["avg_e1"] <= 1]
    if len(duel) >= 2 and f["run_style"] == "E" and any(x["pgm"] == f["pgm"] for x in duel):
        return -0.5, f"E1 {f['avg_e1']}: {len(duel)} E types matched on the lead (#{', #'.join(x['pgm'] for x in duel)})"
    return None


@rule("P10", "Same-day bias from earlier results", "pace", 2.5)
def p10(f, ctx):
    """Only when results of earlier races today are supplied (pick.py --results).  Among winners of the earlier races
    on today's surface (3+ of them): if 75%+ were early types (E, E/P) the early types get +0.6 and the late types
    (P, S) -0.4; if 75%+ were late types the reverse.  If 75%+ of those winners came from posts 1-3, posts 1-3 get
    +0.3 and posts 8+ -0.3; if 75%+ came from posts 8+ the reverse.
    Basis: Davidowitz / Beyer - a bias that shows up in the day's results is the most current information available
    and overrides the meet-long bias stats; three races is the minimum before acting on it."""
    db = ctx.get("day_bias")
    if not db or db["n"] < 3:
        return None
    pts, notes = 0.0, []
    n = db["n"]
    if db["early_wins"] / n >= 0.75:
        pts += 0.6 if f["early_type"] else -0.4
        notes.append(f"{db['early_wins']} of {n} earlier {ctx['race']['surface']} winners were early types")
    elif db["late_wins"] / n >= 0.75:
        pts += 0.6 if f["closer_type"] else -0.4
        notes.append(f"{db['late_wins']} of {n} earlier {ctx['race']['surface']} winners were closers")
    post = f["post"]
    if post is not None:
        if db["inside_wins"] / n >= 0.75:
            pts += 0.3 if post <= 3 else (-0.3 if post >= 8 else 0.0)
            notes.append(f"{db['inside_wins']} of {n} winners from posts 1-3")
        elif db["outside_wins"] / n >= 0.75:
            pts += 0.3 if post >= 8 else (-0.3 if post <= 3 else 0.0)
            notes.append(f"{db['outside_wins']} of {n} winners from posts 8+")
    return (pts, "; ".join(notes)) if pts else None


# =========================================================================
# F — FORM
# =========================================================================
@rule("F1", "Won last race", "form", 3)
def f1(f, ctx):
    """Won last start: 1.0; won 'handily/drew off/driving' (strong win comment): 1.4.
    Basis: Davidowitz / Litfin - last-out winners are in form, and the manner of victory (comment) says how much."""
    if f["last_won"]:
        return (1.4 if f["last_strong_win"] else 1.0), "won last" + (" impressively" if f["last_strong_win"] else "")
    return None


@rule("F2", "In the money last race", "form", 2)
def f2(f, ctx):
    """Finished 2nd or 3rd last time beaten <= 3 lengths: 1.0; 4th-5th beaten <= 3 lengths: 0.5.
    Basis: Ainslie / Davidowitz - a close finish last out is the simplest evidence of current form."""
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
    horse still finished within 6 lengths: 1.0 (excuse); trouble and beaten > 6: 0.4.
    Basis: Beyer trip handicapping - the running-line comment is the only trip note in the PPs; a troubled horse
    that still finished close ran better than its figure."""
    if not f["last_trouble"]:
        return None
    if f["last_beaten"] is not None and f["last_beaten"] <= 6:
        return 1.0, f"trouble: '{f['last_comment']}'"
    return 0.4, f"trouble: '{f['last_comment']}'"


@rule("F4", "Closed ground late last out", "form", 2)
def f4(f, ctx):
    """Gained 2+ lengths from the second call to the finish last time, or passed horses in the stretch: 1.0.
    Basis: Brohamer / Litfin - a horse finishing with energy is improving or suited to a longer trip."""
    if f["last_closed_lengths"] is not None and f["last_closed_lengths"] >= 2:
        return 1.0, f"closed {f['last_closed_lengths']}L from 2nd call"
    if f["last_gained_late"]:
        return 0.5, "passed horses in the stretch"
    return None


@rule("F5", "Bad effort last out", "form", 3)
def f5(f, ctx):
    """Last race comment is negative (faded, tired, no factor, eased, stopped...) and beaten 8+ lengths
    with no trouble: -1.0.  Beaten 15+: -1.5.
    Not applied when the last race was on another surface and the horse has form on today's (S10 excuses it).
    Basis: Davidowitz - a no-excuse thrashing is a form (or soundness) warning until the horse shows otherwise."""
    if f["last_beaten"] is None or f["last_trouble"] or f["use_surface_figs"]:
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
    >= 18% and 4+ works (then -0.3).  <= 14 days ('quick back'): +0.3 if last race was good.
    Basis: Litfin / Brisnet layoff trainer stats - layoff horses win when the barn has a record of winning off the bench
    and the work tab shows a foundation; otherwise they need a race."""
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
    6 lengths; third start: +0.5.
    Basis: Litfin / Brisnet - the second start off a layoff is the classic improvement spot (Brisnet prints it as a
    positive comment); the third is still positive."""
    n = f["races_since_layoff"]
    if n == 1 and f["last_beaten"] is not None and f["last_beaten"] <= 6:
        return 1.0, "2nd off the layoff"
    if n == 2:
        return 0.5, "3rd off the layoff"
    return None


@rule("F8", "Consistency", "form", 3)
def f8(f, ctx):
    """Career ITM% >= 60 with 4+ starts: 1.0; >= 45: 0.5; <= 20% with 8+ starts: -0.7.
    Basis: Ainslie consistency - honest horses keep finishing; chronic non-triers keep not finishing."""
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
    no workout since a layoff of 45+ days: -0.5.
    Basis: Davidowitz / Litfin - bullet and sharp works signal readiness; a layoff horse without works is not ready."""
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
    """ITM in each of the last two starts: 1.0; last three: 1.5.
    Basis: Ainslie - current consistency; horses in a good cycle tend to stay in it for a few starts."""
    if f["itm_streak"] >= 3:
        return 1.5, "ITM last 3"
    if f["itm_streak"] >= 2:
        return 1.0, "ITM last 2"
    return None


@rule("F11", "Trouble in two of the last three", "form", 2)
def f11(f, ctx):
    """The running-line comments show trouble (steadied, checked, blocked, 4+ wide, bumped, slow start...) in two or
    more of the last three starts, each time finishing within 5 lengths: +1.0.  Such a horse's figures understate it.
    Basis: Beyer trip handicapping - repeated trouble is the classic source of a hidden, under-bet horse."""
    if f["trouble_last3"] >= 2:
        return 1.0, f"trouble in {f['trouble_last3']} of last 3 while finishing close"
    return None


@rule("F12", "Hard effort against pace pressure", "form", 2)
def f12(f, ctx):
    """Last race the horse dueled / pressed / set the pace (comment or 1st-2nd at the first call within a length) and
    still finished within 3 lengths: +1.0; within 6: +0.4.  Not awarded to winners (F1 covers them).
    Basis: Brohamer / Beyer - a horse that fought on the lead and held on ran harder than its figure shows; if today's
    pace is softer it improves."""
    if f["last_won"] or not f["last_dueled"] or f["last_beaten"] is None:
        return None
    if f["last_beaten"] <= 3:
        return 1.0, f"dueled and finished {f['last_beaten']}L back"
    if f["last_beaten"] <= 6:
        return 0.4, f"dueled, beaten {f['last_beaten']}L"
    return None


@rule("F13", "Beaten favourite last out", "form", 2.5)
def f13(f, ctx):
    """Was the favourite last time and lost.  With an excuse (trouble, wide trip, a duel) or beaten 2 lengths or less:
    +1.0 (the public was right about the horse and it is likely to be a fair price now).  Beaten 5+ lengths with no
    excuse: -0.6.  A Brisnet "Btn favorite" trainer stat of 20%+ (10+ starts) adds 0.3.
    Basis: Davidowitz - beaten favourites with excuses are among the best-value plays next out; Brisnet prints the
    "Failed as favorite" negative and the trainer's beaten-favourite record for exactly this reason."""
    if not f["last_beaten_favorite"] or f["last_beaten"] is None:
        return None
    excuse = f["last_trouble"] or f["last_wide"] or f["last_dueled"]
    stat = next((t for t in f["trainer_angles"] if re.search(r"[Bb]tn fav", t["category"]) and t["starts"] >= 10), None)
    bonus = 0.3 if stat and stat["win_pct"] >= 20 else 0.0
    if excuse or f["last_beaten"] <= 2:
        return 1.0 + bonus, f"beaten favourite ({f['last_beaten']}L) with " + ("an excuse: '" + f["last_comment"] + "'" if excuse else "a close finish")
    if f["last_beaten"] >= 5:
        return -0.6 + bonus, f"failed as favourite, beaten {f['last_beaten']}L without excuse"
    return None


@rule("F14", "Freshened after a declining cycle", "form", 2)
def f14(f, ctx):
    """Three straight declining figures, then 28-60 days off with two or more workouts since the last race: +0.7
    (the barn stopped on the horse and brought it back fresh).
    Basis: Litfin form cycles - a short freshening after a decline is a deliberate reset, not a layoff."""
    if f["freshened"]:
        return 0.7, f"{f['days_since']} days off after declining figures, {f['works_since_last']} works since"
    return None


@rule("F15", "Fast figure in a losing effort", "form", 2)
def f15(f, ctx):
    """Lost last time by 4+ lengths but earned a figure at least 2 points above today's par (the field it met was
    simply faster): +0.6.  The finish position understates the horse against today's par.
    Basis: Beyer - judge the figure, not the finish; losing fast is better than winning slow."""
    if f["last_lost_fast"]:
        return 0.6, f"beaten {f['last_beaten']}L but ran {f['last_speed']} vs par {ctx['par_speed']}"
    return None


@rule("F16", "Exits a key race", "form", 3)
def f16(f, ctx):
    """Only when the Brisnet Power Play sheet is supplied (pick.py --sheet).  The sheet flags the horse's last race
    as a key race - one whose other runners have already come back to win: "ExitKeyRace" +1.0, "ExitPossibleKeyRace"
    +0.6.  Discounted by half if the horse was beaten 10+ lengths in that race (it was not part of the key race's
    strength).
    Basis: Davidowitz - the key race is the strongest form angle there is, and the one the PPs alone cannot show
    because it needs the other horses' next-out results; Brisnet computes it from its database."""
    if not (f["key_race"] or f["possible_key_race"]):
        return None
    fac = 1.0 if f["key_race"] else 0.6
    why = "key race" if f["key_race"] else "possible key race"
    if f["last_beaten"] is not None and f["last_beaten"] >= 10:
        fac *= 0.5
        why += f" (but beaten {f['last_beaten']}L in it)"
    return fac, f"exits a {why} per the Power Play sheet"


# =========================================================================
# K — CONNECTIONS
# =========================================================================
@rule("K1", "Trainer win percentage (year)", "connections", 3)
def k1(f, ctx):
    """Trainer's current-year win%: >= 22: 1.0; 17-21: 0.6; 12-16: 0.2; <= 7 (with 30+ starts): -0.8.
    Basis: Davidowitz - trainers are the most predictable element on the page; sub-8% barns lose at every level."""
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
    and win% <= 7: -0.5 each (max -1.0). A '+' flag from Brisnet adds 0.2.
    Basis: Davidowitz trainer patterns - a barn's record in exactly today's situation beats its overall record."""
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
    """Jockey current-year win%: >= 18: 1.0; 13-17: 0.5; <= 6 with 50+ mounts: -0.7.
    Basis: Ainslie / Quirin - riders matter less than trainers, but the leading riders get the live horses."""
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
    """Jockey-with-this-trainer (last 60 days) stat: 5+ starts and win% >= 25: 1.0; 5+ starts and 0%: -0.5.
    Basis: Davidowitz - a hot jockey/trainer combination is a live-money signal."""
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
    """Brisnet 'Hot Trainer in last 14 days' comment present: 1.0.
    Basis: Davidowitz / Brisnet - barns win in streaks; the comment flags one in progress."""
    for s in f["positives"]:
        if "Hot Trainer" in s:
            return 1.0, s
    return None


@rule("K7", "Trainer meet form", "connections", 1.5)
def k7(f, ctx):
    """Trainer's record at the current meet: 8+ starts and win% >= 25: +1.0; 15+ starts and 0 wins: -0.6.
    Basis: Davidowitz - the meet record is the most current trainer form available."""
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
    """Jockey change to a rider winning >= 15% on the year, after a rider who was not listed: 1.0.
    Basis: Davidowitz - a switch to a leading rider is a statement of intent by the barn."""
    j = f["jockey_year"]
    if f["jockey_switch"] and j and j["win_pct"] >= 15:
        return 1.0, f"switches to {j['win_pct']}% rider"
    return None


# =========================================================================
# D — DISTANCE / SURFACE
# =========================================================================
@rule("D1", "Record at today's distance", "distance", 3)
def d1(f, ctx):
    """Starts at today's distance: a win: 1.0; ITM (no win) in 2+ tries: 0.5; 0-for-4+ with no ITM: -0.6.
    Basis: Quinn distance preferences - proven at the trip is a credential; repeatedly failing at it is a warning."""
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
    0 for 6+ with ITM% < 20: -0.7.
    Basis: Quinn / Davidowitz - surface preference is one of the few stable traits a horse has."""
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
    (win% >= 20: +0.5).
    Basis: Brisnet pedigree ratings and trainer surface-switch stats are the only evidence for a first-timer on a surface."""
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
    within 3 of the field's best; -0.5 otherwise.
    Basis: Brohamer / Quinn - stretching out suits horses with late pace and stamina pedigree; cutting back suits
    horses with early pace."""
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
    """Won at today's track: 1.0; ITM 2+ times here: 0.5.
    Basis: "horses for courses" - a modest but persistent edge."""
    if f["track_wins"] >= 1:
        return 1.0, f"{f['track_wins']} win(s) at track"
    if f["track_itm"] >= 2:
        return 0.5, f"ITM {f['track_itm']} times at track"
    return None


@rule("D6", "Turf pedigree / proven turf speed (turf races only)", "distance", 2)
def d6(f, ctx):
    """Turf race: best turf figure ranks 1st: +1.0; horse with 0 turf starts and pedigree turf rating < 100: -0.8.
    Basis: Beyer / Quinn - turf form is a separate skill; use turf figures for turf races and pedigree for first-timers."""
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
    scale-of-weights allowance and is still maturing): +0.3.
    Basis: Ainslie - weight matters little, age-and-weight concessions in autumn a little more."""
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
    """Blinkers added today: trainer '1stTimeBlinkers' win% >= 15 (10+ starts): +1.0; <= 7: -0.6; otherwise +0.2.
    Basis: Davidowitz - equipment changes mean what the trainer's record with them says they mean."""
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
    """Blinkers removed today (often a horse that was too keen): +0.3 for P/S types, 0 otherwise.
    Basis: Davidowitz - blinkers off is used to settle a horse that has been rank or pulling."""
    if f["blinkers_off"] and f["closer_type"]:
        return 0.3, "blinkers off"
    return None


@rule("E3", "First-time Lasix", "equipment", 1)
def e3(f, ctx):
    """First-time Lasix (typically a foreign import or a 2yo): +0.5.
    Basis: a small, well-documented first-time improvement; today mostly a foreign-import angle."""
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


@rule("Q1", "QuickPlay positive comments", "comments", 0.8)
def q1(f, ctx):
    """Each Brisnet positive (ñ) comment: +0.5; strong ones (speed rating best in field, class drop, hot trainer...): +1.0. Max 3.0.
    Weight is modest because the comments restate facts the S/C/P/F/K rules already score.
    Basis: Brisnet QuickPlay comments are a rule-based summary of the PPs; experts use them as a first scan and a
    tie-breaker, not as the handicapping itself."""
    pts, notes = 0.0, []
    for s in f["positives"]:
        pts += 1.0 if any(k.lower() in s.lower() for k in STRONG_POS) else 0.5
        notes.append(s)
    pts = min(pts, 3.0)
    return (pts, "; ".join(notes)) if pts else None


@rule("Q2", "QuickPlay negative comments", "comments", 0.8)
def q2(f, ctx):
    """Each Brisnet negative (×) comment: -0.5; strong ones (poor figures, always far back, beaten by weaker, poor trainer...): -1.0.
    Min -3.0.  The generic 'Has not raced for more than 2 months' counts only -0.25 (layoffs are handled by F6).
    Basis: as Q1 - negatives are a cross-check on the other rules, weighted so they cannot outvote them."""
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
    fewer than 3 works (-0.5).
    Basis: Litfin / Davidowitz - debut runners are judged on the barn's debut record, the sire's precocity and the
    work tab; a debut in a maiden claimer says the barn does not think much of the horse."""
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
    maiden claimers with a speed figure within 4 of today's par: +1.0 (the classic MSW-to-MCL drop).
    Basis: Davidowitz / Quinn - MSW to maiden-claiming is the biggest class drop in racing."""
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
    """Maiden with 8+ starts: -0.8; 12+ starts: -1.2.  Maiden with 3+ seconds and no win ('sucker horse'): additional -0.4.
    Basis: Davidowitz / Quinn - chronic maidens, especially habitual runners-up, are the classic underlay."""
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
    second career start after a debut within 4 lengths, or with a debut figure within 5 of today's par: +0.6
    (second-time starters improve on average; a near-par debut makes par reachable today).  Not awarded for a
    third-start leap of 8+ points that is also a career top (that is S6's bounce pattern).
    Basis: Litfin - lightly raced horses improve more and more often than seasoned ones; the second start is the
    biggest average step forward."""
    if f["first_time_starter"] or f["starts"] > 3:
        return None
    s = f["speed_last3"]
    if len(s) >= 2 and s[0] >= s[1] + 5:
        if f["career_top_last"] and f["starts"] >= 3 and s[0] - s[1] >= 8:
            return None   # a 3rd-start leap of 8+ is the bounce pattern S6 scores, not an improvement cycle
        return 1.0, f"improved {s[1]}->{s[0]}"
    if f["starts"] == 1:
        par = ctx["par_speed"]
        if f["last_beaten"] is not None and f["last_beaten"] <= 4:
            return 0.6, f"2nd start, debut beaten {f['last_beaten']}L"
        if par and f["debut_speed"] is not None and f["debut_speed"] >= par - 5:
            return 0.6, f"2nd start, debut figure {f['debut_speed']} vs par {par}"
    return None


# =========================================================================
# X — ELIMINATIONS (hard filters; factor -1 marks the horse as a throw-out)
# =========================================================================
@rule("X1", "Hopelessly slow", "elimination", 1, hard=True)
def x1(f, ctx):
    """Throw-out: best speed figure of the last three starts is 10+ points below today's par AND the horse has
    3+ starts AND it is not dropping 3+ class levels AND its best figure under today's surface/distance conditions
    (last four such races) is not within 4 of par either.
    Basis: Beyer / Quinn - eliminate horses whose figures cannot reach par; the process starts by throwing out.
    Beyer again for the exemption: a figure earned under today's conditions outranks recent figures earned elsewhere
    (Belmont 2026-11-06 R2: the winner had run 89 at the distance but 75-76 since, and was thrown out)."""
    par = ctx["par_speed"]
    if par and f["best_last3"] is not None and f["starts"] >= 3 and f["best_last3"] <= par - 10:
        if f["class_move"] is not None and f["class_move"] <= -3:
            return None
        if f["best_match_speed"] is not None and f["best_match_speed"] >= par - 4:
            return None
        return -1.0, f"best of last 3 {f['best_last3']} is {par - f['best_last3']} below par {par}"
    return None


@rule("X2", "Long layoff, no foundation", "elimination", 1, hard=True)
def x2(f, ctx):
    """Throw-out: 365+ days since last race with fewer than 4 workouts.
    Basis: Litfin / Davidowitz - a year away without a foundation of works is a horse not meant to win today."""
    if f["days_since"] is not None and f["days_since"] >= 365 and f["num_works"] < 4:
        return -1.0, f"{f['days_since']} days off, {f['num_works']} works"
    return None


@rule("X3", "Also-eligible / main-track-only", "elimination", 1, hard=True)
def x3(f, ctx):
    """Flag (not a throw-out): horse is on the also-eligible list or main-track-only; it runs only if scratches occur.
    Scored normally but reported with an AE/MTO flag.
    Basis: Crist - never build a ticket around a horse that may not run."""
    if f["entry_status"]:
        return 0.0, f"{f['entry_status']} - needs a scratch to run"
    return None


@rule("X4", "Badly outclassed", "elimination", 1, hard=True)
def x4(f, ctx):
    """Throw-out: average class rating of the last three starts is 8+ points below the field's best AND
    the horse is not dropping in class.
    Basis: Quinn - a horse that has only met far weaker fields and is not dropping is outclassed."""
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
    Chalk at 6/5 or lower never gets a value bonus.
    Basis: Meadow / Crist - make your own line and bet only overlays; the morning line is a stand-in for the public's
    line until the real odds are known."""
    return None   # evaluated by the engine with knowledge of the whole field
