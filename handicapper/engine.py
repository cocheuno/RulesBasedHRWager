"""
Scoring engine + selection policy.

score(race) -> list of horse scoresheets (sorted best first), each with the
full audit trail of rule hits, plus the race-level selection (1-3 horses)
and a suggested bet structure.

Selection policy (all thresholds in rules_config.json -> "selection"):
  * hard eliminations (X rules with factor < 0) are removed from contention
    but still listed in the audit.
  * confidence = gap between the top score and the next contender,
    expressed in points.  A single is played when the gap >= single_gap
    and the top horse is not a hopeless underlay; two horses when the
    2nd is within pair_gap of the top; three otherwise (or when the race
    is contentious: 4+ horses within spread_gap of the leader).
  * races with fewer than min_field contenders are still scored but the
    report marks them "thin".
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict

from . import rules as R
from . import multirace as MR
from .features import horse_features, race_context

DEFAULT_CONFIG = {
    "weights": {},                 # rule id -> weight override
    "disabled": [],                # rule ids switched off
    "selection": {
        "single_gap": 7.0,         # points clear of 2nd => 1-horse play
        "pair_gap": 4.0,           # 2nd within this of 1st => include
        "third_gap": 7.0,          # 3rd within this of 1st => include
        "spread_gap": 4.0,         # 4+ horses within this => contentious
        "max_picks": 3,
        "min_ml_for_win_bet": 1.5,  # <= 6/5 ML: no win bet, exotics only
        "value_overlay": 1.30,
        "value_underlay": 0.60,
        "logit_scale": 12.0,       # points per e-fold in implied probability
    },
    "multirace": dict(MR.DEFAULT_MULTIRACE),   # Pick 3 / Pick 4 construction (see multirace.py)
}


def load_config(path: str | None) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if path and os.path.exists(path):
        user = json.load(open(path, encoding="utf-8"))
        cfg["weights"].update(user.get("weights", {}))
        cfg["disabled"] = user.get("disabled", cfg["disabled"])
        cfg["selection"].update(user.get("selection", {}))
        for k, v in user.get("multirace", {}).items():
            if isinstance(v, dict) and isinstance(cfg["multirace"].get(k), dict):
                cfg["multirace"][k].update(v)
            else:
                cfg["multirace"][k] = v
    return cfg


def implied_probs(scores: dict[str, float], scale: float) -> dict[str, float]:
    """Softmax over scores: p_i = exp(s_i/scale) / sum."""
    if not scores:
        return {}
    m = max(scores.values())
    ex = {k: math.exp((v - m) / scale) for k, v in scores.items()}
    z = sum(ex.values())
    return {k: v / z for k, v in ex.items()}


def score_race(race: dict, cfg: dict) -> dict:
    feats = {h["pgm"]: horse_features(h, race) for h in race["horses"]}
    ctx = race_context(race, feats)
    sel = cfg["selection"]
    sheets = []
    for h in race["horses"]:
        f = feats[h["pgm"]]
        hits, total, eliminated, flags = [], 0.0, False, []
        for rl in R.RULES:
            if rl.id in cfg["disabled"]:
                continue
            w = cfg["weights"].get(rl.id, rl.weight)
            try:
                res = rl.fn(f, ctx)
            except Exception as e:  # a rule bug must never kill the run; record it
                hits.append({"rule": rl.id, "name": rl.name, "points": 0.0, "note": f"RULE ERROR {e!r}"})
                continue
            if res is None:
                continue
            factor, note = res
            if factor is None:
                continue
            if rl.hard:
                if factor < 0:
                    eliminated = True
                    hits.append({"rule": rl.id, "name": rl.name, "points": 0.0, "note": "ELIMINATED: " + note})
                else:
                    flags.append(note)
                    hits.append({"rule": rl.id, "name": rl.name, "points": 0.0, "note": "FLAG: " + note})
                continue
            pts = round(factor * w, 2)
            if pts == 0:
                continue
            total += pts
            hits.append({"rule": rl.id, "name": rl.name, "points": pts, "note": note})
        sheets.append({
            "pgm": h["pgm"], "name": h["name"], "ml_odds": h["ml_odds"], "ml_decimal": h["ml_decimal"],
            "run_style": h["run_style"], "speed_pts": h["speed_pts"], "prime_power": h["prime_power"],
            "score": round(total, 2), "eliminated": eliminated, "flags": flags, "hits": hits,
            "features": {k: v for k, v in f.items() if not k.startswith("_") and k not in ("last", "positives", "negatives", "trainer_angles", "trainer_flagged")},
        })
    # ---- value rule (V1): compare score-implied probability to ML
    live = {s["pgm"]: s["score"] for s in sheets if not s["eliminated"]}
    probs = implied_probs(live, sel["logit_scale"])
    w_v1 = cfg["weights"].get("V1", next(r.weight for r in R.RULES if r.id == "V1"))
    for s in sheets:
        s["implied_prob"] = round(probs.get(s["pgm"], 0.0), 3)
        s["fair_odds"] = round((1 - s["implied_prob"]) / s["implied_prob"], 1) if s["implied_prob"] > 0.001 else None
        if s["eliminated"] or s["ml_decimal"] is None or s["fair_odds"] is None or "V1" in cfg["disabled"]:
            continue
        ml = s["ml_decimal"]
        if ml >= s["fair_odds"] * sel["value_overlay"] and ml > 1.2:
            pts = round(1.0 * w_v1, 2)
            s["score"] = round(s["score"] + pts, 2)
            s["hits"].append({"rule": "V1", "name": "Morning-line value", "points": pts, "note": f"overlay: ML {s['ml_odds']} vs fair {s['fair_odds']}-1"})
        elif ml <= s["fair_odds"] * sel["value_underlay"]:
            pts = round(-0.8 * w_v1, 2)
            s["score"] = round(s["score"] + pts, 2)
            s["hits"].append({"rule": "V1", "name": "Morning-line value", "points": pts, "note": f"underlay: ML {s['ml_odds']} vs fair {s['fair_odds']}-1"})
    sheets.sort(key=lambda s: (s["eliminated"], -s["score"]))
    for i, s in enumerate(sheets, 1):
        s["rank"] = i
    picks, structure, confidence, note = select(sheets, sel)
    return {
        "race_no": race["race_no"], "class_text": race.get("class_text"), "distance_text": race.get("distance_text"),
        "surface": race.get("surface"), "field_size": len(race["horses"]), "pars": race.get("pars"),
        "pace_shape": ctx["pace_shape"], "lone_speed": ctx["lone_speed"], "num_early": ctx["num_early"],
        "picks": picks, "bet_structure": structure, "confidence": confidence, "selection_note": note,
        "sheets": sheets,
    }


def select(sheets: list[dict], sel: dict):
    # also-eligible / MTO horses cannot be relied on to run: they are reported as conditional alternates
    ae = [s for s in sheets if not s["eliminated"] and s["flags"]]
    live = [s for s in sheets if not s["eliminated"] and not s["flags"]]
    if not live:
        return [], "PASS", "none", "no contenders survive the eliminations"
    picks, structure, confidence, note = _select_live(live, sel)
    for s in ae:
        if s["rank"] <= 3:
            note += f"; #{s['pgm']} {s['name']} (AE, rank {s['rank']}) would be a play if it draws in"
    return picks, structure, confidence, note


def _select_live(live: list[dict], sel: dict):
    top = live[0]
    gap2 = (top["score"] - live[1]["score"]) if len(live) > 1 else 99.0
    gap3 = (top["score"] - live[2]["score"]) if len(live) > 2 else 99.0
    within_spread = sum(1 for s in live if top["score"] - s["score"] <= sel["spread_gap"])
    contentious = within_spread >= 4
    picks = [top["pgm"]]
    if gap2 >= sel["single_gap"] and not contentious:
        confidence = "high"
        note = f"#{top['pgm']} is {gap2:.1f} points clear"
    else:
        if gap2 <= sel["pair_gap"] or contentious:
            picks.append(live[1]["pgm"])
        elif len(live) > 1 and gap2 < sel["single_gap"]:
            picks.append(live[1]["pgm"])
        if len(live) > 2 and (gap3 <= sel["third_gap"]) and len(picks) < sel["max_picks"]:
            picks.append(live[2]["pgm"])
        confidence = "low" if contentious else "medium"
        note = f"gap to 2nd {gap2:.1f}, to 3rd {gap3:.1f}" + (", contentious" if contentious else "")
    picks = picks[: sel["max_picks"]]
    # bet structure
    ml = top["ml_decimal"] or 99
    if len(picks) == 1:
        structure = "WIN" if ml >= sel["min_ml_for_win_bet"] else "KEY in exactas/trifectas (ML too short for a win bet)"
    elif len(picks) == 2:
        a, b = picks
        structure = f"EXACTA box {a}-{b}; WIN on the longer-priced of the two if ML >= 5/2"
    else:
        structure = f"TRIFECTA box {'-'.join(picks)}; EXACTA box top two; WIN on #{picks[0]}" if ml >= sel["min_ml_for_win_bet"] else f"TRIFECTA box {'-'.join(picks)}; EXACTA {picks[0]} over {picks[1]},{picks[2]}"
    return picks, structure, confidence, note


def score_card(card: dict, cfg: dict, multirace: bool = True) -> dict:
    out = {"source": card.get("source"), "track": card.get("track"), "date": card.get("date"), "races": []}
    for race in card["races"]:
        out["races"].append(score_race(race, cfg))
    out["multirace"] = MR.build_all(out, cfg["multirace"]) if multirace else None
    return out


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------
def format_report(result: dict, detail: int = 1) -> str:
    L = []
    L.append(f"# {result.get('track')} — {result.get('date')}  (picks generated by rules engine)")
    L.append("")
    for r in result["races"]:
        L.append(f"## Race {r['race_no']}: {r['class_text']}  {r['distance_text']} ({r['surface']})  field {r['field_size']}  pars {r['pars']}")
        L.append(f"Pace shape: {r['pace_shape']} (early types: {r['num_early']}" + (f", lone speed #{r['lone_speed']}" if r["lone_speed"] else "") + ")")
        names = {s["pgm"]: s for s in r["sheets"]}
        L.append(f"**PLAY: {', '.join('#' + p + ' ' + names[p]['name'] + ' (' + str(names[p]['ml_odds']) + ')' for p in r['picks'])}**  — {r['bet_structure']}")
        L.append(f"Confidence: {r['confidence']} — {r['selection_note']}")
        L.append("")
        L.append("| Rk | # | Horse | ML | Style/pts | PP | Score | Prob | Fair | Top reasons |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for s in r["sheets"]:
            hits = sorted([h for h in s["hits"] if h["points"]], key=lambda h: -abs(h["points"]))
            top = "; ".join(f"{h['rule']} {h['points']:+.1f} {h['note'][:60]}" for h in hits[:4 if detail else 2])
            elim = " **ELIM**" if s["eliminated"] else ""
            flag = (" [" + "; ".join(s["flags"]) + "]") if s["flags"] else ""
            L.append(f"| {s['rank']} | {s['pgm']} | {s['name']}{elim}{flag} | {s['ml_odds']} | {s['run_style']}/{s['speed_pts']} | {s['prime_power']} | {s['score']:.1f} | {s['implied_prob']:.0%} | {s['fair_odds']} | {top} |")
        L.append("")
        if detail >= 2:
            for s in r["sheets"]:
                L.append(f"### #{s['pgm']} {s['name']} — {s['score']:.1f}")
                for h in s["hits"]:
                    L.append(f"- {h['rule']} {h['name']}: {h['points']:+.2f} — {h['note']}")
                L.append("")
    if result.get("multirace"):
        L.append(MR.format_multirace(result["multirace"], result, detail))
    return "\n".join(L)


def rules_doc() -> str:
    L = ["# Handicapping rule catalog", "", "Points = factor × weight. Weights are defaults; override in rules_config.json.", ""]
    cats = defaultdict(list)
    for rl in R.RULES:
        cats[rl.category].append(rl)
    for cat, rls in cats.items():
        L.append(f"## {cat.title()}")
        L.append("")
        L.append("| Id | Rule | Weight | Definition |")
        L.append("|---|---|---|---|")
        for rl in rls:
            L.append(f"| {rl.id} | {rl.name} | {rl.weight}{' (hard)' if rl.hard else ''} | {' '.join(rl.doc.split())} |")
        L.append("")
    L.append("## Horizontal (Pick 3 / Pick 4 construction)")
    L.append("")
    L.append("These rules grade legs and build tickets from the scored races (handicapper/multirace.py); "
             "thresholds live in rules_config.json -> multirace.")
    L.append("")
    L.append("| Id | Rule | Definition |")
    L.append("|---|---|---|")
    for rl in MR.HRULES:
        L.append(f"| {rl.id} | {rl.name} | {' '.join(rl.doc.split())} |")
    L.append("")
    return "\n".join(L)
