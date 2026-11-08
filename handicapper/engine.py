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
from .probability import DEFAULT_PROBABILITY, fair_odds, race_probs
from .probability import DEFAULT_PROBABILITY, fair_odds, race_probs
from .wagering import DEFAULT_UNITS, DEFAULT_WAGERING, make_wager
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
        "win_margin": 0.15,        # a win bet also needs odds >= fair odds x (1 + margin): no bet at or under fair
        "value_overlay": 1.30,     # V1 overlay: ML >= fair x 1.30
        "value_underlay": 0.60,    # V1 underlay: ML <= fair x 0.60
    },
    "probability": dict(DEFAULT_PROBABILITY),  # the one win-probability model (see probability.py)
    "multirace": dict(MR.DEFAULT_MULTIRACE),   # Pick 3 / Pick 4 construction (see multirace.py)
    "wagering": dict(DEFAULT_WAGERING),        # unit stake and what counts as a bet (see wagering.py)
}


def _apply_layer(cfg: dict, layer: dict) -> None:
    """Overlay one config layer (the global file, or one track profile) onto cfg."""
    cfg["weights"].update(layer.get("weights", {}))
    if "disabled" in layer:
        cfg["disabled"] = list(layer["disabled"])
    cfg["selection"].update(layer.get("selection", {}))
    cfg["probability"].update(layer.get("probability", {}))
    for k, v in layer.get("multirace", {}).items():
        if isinstance(v, dict) and isinstance(cfg["multirace"].get(k), dict):
            cfg["multirace"][k].update(v)
        else:
            cfg["multirace"][k] = v
    cfg["wagering"].update(layer.get("wagering", {}))


def load_config(path: str | None, track_code: str | None = None) -> dict:
    """Global defaults <- rules_config.json <- rules_config.json["tracks"][track_code].

    Weights, thresholds and ticket parameters are track-specific priors; the profile is chosen from the
    track code the parser reads off the PP (card["track_code"]), or from --track-profile.  Unknown track:
    the global layer only, reported as profile "default"."""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["tracks"], cfg["track_aliases"] = {}, {}
    if path and os.path.exists(path):
        user = json.load(open(path, encoding="utf-8"))
        _apply_layer(cfg, user)
        cfg["tracks"] = user.get("tracks", {})
        cfg["track_aliases"] = user.get("track_aliases", {})
    cfg["track_profile"] = "default"
    code = (track_code or "").upper()
    if code and code in cfg["tracks"]:
        _apply_layer(cfg, cfg["tracks"][code])
        cfg["track_profile"] = code
    elif code:
        cfg["track_profile"] = f"default (no profile for {code})"
    return cfg


def resolve_track_code(card: dict, cfg: dict) -> str | None:
    """The card's track code (parser), else the track name mapped through rules_config.json["track_aliases"]."""
    code = card.get("track_code")
    if code:
        return code.upper()
    name = (card.get("track") or "").strip().lower()
    for alias, c in cfg.get("track_aliases", {}).items():
        if alias.lower() == name:
            return c.upper()
    return None


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
    # ---- probabilities: one model for the race, over the horses that can win (not eliminated, not AE/MTO)
    live = [s for s in sheets if not s["eliminated"] and not s["flags"]]
    pr = race_probs(live, cfg.get("probability"))
    for s in sheets:
        s["model_prob"] = pr["model"].get(s["pgm"], 0.0)
        s["market_prob"] = (pr["market"] or {}).get(s["pgm"])
        s["win_prob"] = pr["win"].get(s["pgm"], 0.0)
        s["implied_prob"] = s["model_prob"]                 # older name, kept for readers of picks.json
        s["fair_odds"] = fair_odds(s["model_prob"]) if s["pgm"] in pr["model"] else None
        s["value"] = None
    # ---- value (V1): the engine's fair odds against the morning line.  Reported beside the score, never in it:
    # the ability rank must not move because the price is generous or short.
    w_v1 = cfg["weights"].get("V1", next(r.weight for r in R.RULES if r.id == "V1"))
    for s in live:
        if s["ml_decimal"] is None or s["fair_odds"] is None or "V1" in cfg["disabled"]:
            continue
        ml, fair = s["ml_decimal"], s["fair_odds"]
        edge = round(ml / fair - 1.0, 2) if fair else None
        if ml >= fair * sel["value_overlay"] and ml > 1.2:
            pts, label = round(1.0 * w_v1, 2), "overlay"
        elif ml <= fair * sel["value_underlay"]:
            pts, label = round(-0.8 * w_v1, 2), "underlay"
        else:
            s["value"] = {"label": "fair", "points": 0.0, "edge": edge}
            continue
        s["value"] = {"label": label, "points": pts, "edge": edge}
        s["hits"].append({"rule": "V1", "name": "Morning-line value", "points": pts, "value": True,
                          "note": f"{label}: ML {s['ml_odds']} vs fair {fair}-1 (value, not in the ability score)"})
    sheets.sort(key=lambda s: (s["eliminated"], -s["score"]))
    for i, s in enumerate(sheets, 1):
        s["rank"] = i
        s["min_win_odds"] = None if s["eliminated"] else win_price(s, sel)["min_odds"]
    picks, structure, confidence, note = select(sheets, sel)
    return {
        "race_no": race["race_no"], "class_text": race.get("class_text"), "distance_text": race.get("distance_text"),
        "surface": race.get("surface"), "field_size": len(race["horses"]), "pars": race.get("pars"),
        "pace_shape": ctx["pace_shape"], "lone_speed": ctx["lone_speed"], "num_early": ctx["num_early"],
        "picks": picks, "bet_structure": structure, "confidence": confidence, "selection_note": note,
        "brisnet": race.get("brisnet"), "wagers_menu": race.get("wagers"), "sheets": sheets,
    }


def win_price(s: dict, sel: dict) -> dict:
    """Minimum acceptable odds for a win bet on this horse, and whether the morning line meets it.
    min_odds = max(min_ml_for_win_bet, fair_odds x (1 + win_margin)).  ok is True (bet), False (price too short)
    or None when the PPs carry no morning line: then the price is unknown, the bet is advisory ("take X-1 or
    better on the board") and is never counted as a bet placed.  A missing price is never treated as a long one."""
    floor = float(sel["min_ml_for_win_bet"])
    fair = s.get("fair_odds")
    min_odds = floor if fair is None else max(floor, round(fair * (1 + sel.get("win_margin", 0.0)), 1))
    ml = s.get("ml_decimal")
    out = {"min_odds": min_odds, "ml": ml, "fair": fair}
    if ml is None:
        return out | {"ok": None, "why": f"no morning line in the PPs; take {min_odds:g}-1 or better on the board"}
    if ml < floor:
        return out | {"ok": False, "why": f"ML {s.get('ml_odds')} is below {floor:g}-1"}
    if ml < min_odds:
        return out | {"ok": False, "why": f"ML {s.get('ml_odds')} is under fair {fair}-1 plus margin ({min_odds:g}-1 needed)"}
    return out | {"ok": True, "why": f"ML {s.get('ml_odds')}, take {min_odds:g}-1 or better"}


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
    # bet structure: a win bet only at an acceptable price; no morning line = price unknown, advisory only
    wp = win_price(top, sel)
    if wp["ok"] is True:
        win = f"WIN (take {wp['min_odds']:g}-1 or better)"
    elif wp["ok"] is None:
        win = f"WIN only if the board shows {wp['min_odds']:g}-1 or better (no morning line in the PPs)"
    else:
        win = None
    if len(picks) == 1:
        structure = win if win else f"KEY in exactas/trifectas, no win bet ({wp['why']})"
    elif len(picks) == 2:
        a, b = picks
        structure = f"EXACTA box {a}-{b}; WIN on the longer-priced of the two at 5/2 or better"
    else:
        structure = f"TRIFECTA box {'-'.join(picks)}; EXACTA box top two; " + (win.replace("WIN", f"WIN on #{picks[0]}", 1) if win else f"no win bet on #{picks[0]} ({wp['why']})")
    return picks, structure, confidence, note


def score_card(card: dict, cfg: dict, multirace: bool = True) -> dict:
    out = {"source": card.get("source"), "track": card.get("track"), "track_code": card.get("track_code"),
           "date": card.get("date"), "track_profile": cfg.get("track_profile", "default"), "races": []}
    for race in card["races"]:
        out["races"].append(score_race(race, cfg))
    mr_cfg = dict(cfg["multirace"], probability=cfg.get("probability", DEFAULT_PROBABILITY))
    for r in out["races"]:
        r["leg"] = MR.leg_summary(r, mr_cfg) if multirace else None
    for i, r in enumerate(out["races"]):
        nxt = out["races"][i + 1] if i + 1 < len(out["races"]) else None
        r["wagers"] = primary_wagers(r, cfg["selection"])
        r["other_wagers"] = other_wagers(r, nxt, cfg["selection"], r["wagers"], units=cfg.get("wagering", {}).get("units"))
    out["multirace"] = MR.build_all(out, mr_cfg) if multirace else None
    return out


def primary_wagers(r: dict, sel: dict) -> list[dict]:
    """The primary play as wager structures (mirrors the bet_structure text from select())."""
    p = r["picks"]
    if not p:
        return []
    names = {s["pgm"]: s for s in r["sheets"]}
    wp = win_price(names[p[0]], sel)
    n = r["race_no"]
    W = []

    def win(k, extra=""):
        w = win_price(names[k], sel)
        return make_wager("WIN", [[k]], False, f"WIN #{k}{extra} (take {w['min_odds']:g}-1 or better)", "primary", n) | {"min_odds": w["min_odds"]}

    if len(p) == 1:
        if wp["ok"] is True:
            W.append(win(p[0]))
    elif len(p) == 2:
        W.append(make_wager("EXACTA", [p, p], True, f"EXACTA box #{p[0]}-#{p[1]}", "primary", n))
        priced = [k for k in p if names[k]["ml_decimal"] is not None]
        if len(priced) == 2:                      # the longer-priced of the pair, only when both are priced
            longer = max(priced, key=lambda k: names[k]["ml_decimal"])
            if names[longer]["ml_decimal"] >= 2.5 and win_price(names[longer], sel)["ok"] is True:
                W.append(win(longer, " (longer-priced of the pair)"))
    else:
        W.append(make_wager("TRIFECTA", [p, p, p], True, "TRIFECTA box " + "-".join("#" + k for k in p), "primary", n))
        W.append(make_wager("EXACTA", [p[:2], p[:2]], True, f"EXACTA box #{p[0]}-#{p[1]}", "primary", n))
        if wp["ok"] is True:
            W.append(win(p[0]))
    return W


def other_wagers(r: dict, nxt: dict | None, sel: dict, structs: list | None = None, units: dict | None = None) -> list[str]:
    """Exotic / secondary wagers for one race, built from the ranked live horses, the race confidence and the
    leg grading (A/B, vulnerable favourite) when it is available.  Deterministic; every line names the horses.

    Policy (Crist *Exotic Betting*, Meadow, Davidowitz):
      * high confidence: key the top horse on top of exactas and trifectas (not boxes - a key costs a third of a
        box and the opinion is that the key wins); no WIN bet under 3/2 ML, use it as a horizontal single instead;
        a superfecta key only in 8+ horse fields.
      * medium: exacta box of the top two and a part-wheel over the third; trifecta top two over top three over
        top four; WIN only on a horse V1 marked as an overlay.
      * low / contentious: no win bet unless an overlay; trifecta box of the top three (four when the 4th is
        within spread_gap); treat the race as a spread leg in the Pick 3 / 4.
      * vulnerable favourite (H5): structure exactas with the favourite underneath only.
      * daily double: this race's A horses with the next race's A horses (cost at the configured double unit).
    """
    live = [x for x in r["sheets"] if not x["eliminated"] and not x["flags"]]
    if len(live) < 2:
        return ["PASS: fewer than two live contenders"]
    p = [x["pgm"] for x in live[:5]]
    a, b, c = p[0], p[1], (p[2] if len(p) > 2 else None)
    d = p[3] if len(p) > 3 else None
    e = p[4] if len(p) > 4 else None
    top = live[0]
    wp = win_price(top, sel)
    conf = r["confidence"]
    leg = r.get("leg") or {}
    fav = leg.get("favorite")
    overlays = [x for x in live[:3] if any(h["rule"] == "V1" and h["points"] > 0 for h in x["hits"])]
    W: list[str] = []

    def hs(*ks):
        return ",".join(f"#{k}" for k in ks if k)

    def add(wtype, legs, box=False, races=None):
        """record the structured form of the line just appended to W (skipped when W holds advice only)"""
        if structs is not None:
            structs.append(make_wager(wtype, [[k for k in leg if k] for leg in legs], box, W[-1], "other",
                                      r["race_no"], races))

    if conf == "high":
        W.append(f"EXACTA key {hs(a)} over {hs(b, c, d)}")
        add("EXACTA", [[a], [b, c, d]])
        if c:
            W.append(f"TRIFECTA key {hs(a)} / {hs(b, c, d)} / {hs(b, c, d, e)}")
            add("TRIFECTA", [[a], [b, c, d], [b, c, d, e]])
        if wp["ok"] is True:
            W.append(f"WIN {hs(a)} ({wp['why']}; fair {top['fair_odds']}-1)")
            add("WIN", [[a]])
            structs[-1]["min_odds"] = wp["min_odds"]
        elif wp["ok"] is None:
            W.append(f"WIN {hs(a)} only if the board shows {wp['min_odds']:g}-1 or better (no morning line in the PPs; fair {top['fair_odds']}-1) - not counted as a bet")
        else:
            W.append(f"no WIN bet on {hs(a)} ({wp['why']}): use it as a single in the Pick 3 / Pick 4 instead")
        if r["field_size"] >= 8 and e:
            W.append(f"SUPERFECTA key {hs(a)} / {hs(b, c, d)} / {hs(b, c, d)} / {hs(b, c, d, e)}")
            add("SUPERFECTA", [[a], [b, c, d], [b, c, d], [b, c, d, e]])
    elif conf == "medium":
        W.append(f"EXACTA box {hs(a, b)}" + (f"; EXACTA part-wheel {hs(a, b)} / {hs(a, b, c)}" if c else ""))
        add("EXACTA", [[a, b], [a, b, c]] if c else [[a, b], [a, b]])
        if c:
            W.append(f"TRIFECTA {hs(a, b)} / {hs(a, b, c)} / {hs(a, b, c, d)}")
            add("TRIFECTA", [[a, b], [a, b, c], [a, b, c, d]])
        if overlays:
            W.append("WIN on the overlay: " + "; ".join(f"{hs(x['pgm'])} (ML {x['ml_odds']} vs fair {x['fair_odds']}-1; take {win_price(x, sel)['min_odds']:g}-1 or better)" for x in overlays))
            add("WIN", [[x["pgm"] for x in overlays]])
        else:
            W.append("no WIN bet: neither of the top two is an overlay at the morning line")
    else:
        spread = [x["pgm"] for x in live[:4] if top["score"] - x["score"] <= sel["spread_gap"]]
        box = [k for k in [a, b, c] + ([d] if d and d in spread else []) if k]
        W.append(f"TRIFECTA box {'-'.join('#' + k for k in box)} (contentious: spread, do not key)")
        if len(box) >= 3:
            add("TRIFECTA", [box, box, box], box=True)
        W.append(f"EXACTA box {'-'.join('#' + k for k in box[:3])}")
        add("EXACTA", [box[:3], box[:3]], box=True)
        if overlays:
            W.append("WIN on the overlay: " + "; ".join(f"{hs(x['pgm'])} (ML {x['ml_odds']} vs fair {x['fair_odds']}-1; take {win_price(x, sel)['min_odds']:g}-1 or better)" for x in overlays))
            add("WIN", [[x["pgm"] for x in overlays]])
        else:
            W.append("no WIN bet in a contentious race without an overlay; use the A/B spread in the Pick 3 / Pick 4")
    if leg.get("price_leg") and fav and fav != a:
        over = [k for k in (a, b) if k != fav]
        under = list(dict.fromkeys(k for k in (a, b, c, fav) if k))   # ordered, no duplicates
        W.append(f"favourite {hs(fav)} looks beatable (H5): EXACTA {hs(*over)} over {hs(*under)} - chalk underneath only, never on top")
        add("EXACTA", [over, under])
    if leg.get("A") and nxt and (nxt.get("leg") or {}).get("A"):
        na = nxt["leg"]["A"]
        du = float((units or {}).get("DOUBLE", DEFAULT_UNITS["DOUBLE"]))
        W.append(f"DAILY DOUBLE {hs(*leg['A'])} with R{nxt['race_no']} {hs(*na)} ({len(set(leg['A'])) * len(set(na))} x ${du:g})")
        add("DOUBLE", [list(leg["A"]), list(na)], races=[r["race_no"], nxt["race_no"]])
    return W


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------
def value_text(s: dict) -> str:
    """'overlay +45%' / 'underlay -30%' / 'fair' / '-' (no morning line)."""
    v = s.get("value")
    if not v:
        return "-"
    if v["label"] == "fair" or v.get("edge") is None:
        return v["label"]
    return f"{v['label']} {v['edge']:+.0%}"


def value_text(s: dict) -> str:
    """'overlay +45%' / 'underlay -30%' / 'fair' / '-' (no morning line)."""
    v = s.get("value")
    if not v:
        return "-"
    if v["label"] == "fair" or v.get("edge") is None:
        return v["label"]
    return f"{v['label']} {v['edge']:+.0%}"


def format_summary(result: dict) -> str:
    """The bets only: per race the top three ranked horses, the primary play and the other suggested wagers,
    then the recommended Pick 3 / Pick 4 tickets.  No rule detail."""
    L = ["## Wagering summary", ""]
    for r in result["races"]:
        names = {s["pgm"]: s for s in r["sheets"]}
        live = [s for s in r["sheets"] if not s["eliminated"] and not s["flags"]]
        leg = r.get("leg") or {}
        L.append(f"### Race {r['race_no']}: {r['class_text']}  {r['distance_text']} ({r['surface']})  field {r['field_size']}  — confidence {r['confidence']}")
        L.append("")
        L.append("| Rank | # | Horse | ML | Score | Win chance | Fair | Value | Grade |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for i, s in enumerate(live[:3], 1):
            grade = "A" if s["pgm"] in leg.get("A", []) else ("B" if s["pgm"] in leg.get("B", []) else "-")
            L.append(f"| {i} | {s['pgm']} | {s['name']} | {s['ml_odds']} | {s['score']:.1f} | {s['win_prob']:.0%} | {s['fair_odds']} | {value_text(s)} | {grade} |")
        play = ", ".join(f"#{p} {names[p]['name']} ({names[p]['ml_odds']})" for p in r["picks"]) or "PASS"
        L.append("")
        L.append(f"**Primary play:** {play} — {r['bet_structure']}")
        L.append("")
        L.append("Other wagers:")
        for w in r.get("other_wagers", []):
            L.append(f"- {w}")
        L.append("")
    mr = result.get("multirace") or {}
    for key in ("pick3", "pick4"):
        rec = (mr.get(key) or {}).get("recommended")
        if not rec:
            continue
        L.append(f"**{rec['name']}** — ${rec['cost']:.2f} total (${rec['base']:.2f} base), hit probability {rec['hit_prob']:.0%}")
        for t in rec["tickets"]:
            L.append(f"- {t['name']}: " + " / ".join(",".join(x) for x in t["legs"]) + f"  (${t['cost']:.2f})")
        L.append("")
    return "\n".join(L)


def format_report(result: dict, detail: int = 1) -> str:
    L = []
    L.append(f"# {result.get('track')} — {result.get('date')}  (picks generated by rules engine; track profile: {result.get('track_profile', 'default')})")
    L.append("")
    L.append(format_summary(result))
    if detail <= 0:
        return "\n".join(L)
    L.append("## Race details")
    L.append("")
    for r in result["races"]:
        L.append(f"## Race {r['race_no']}: {r['class_text']}  {r['distance_text']} ({r['surface']})  field {r['field_size']}  pars {r['pars']}")
        L.append(f"Pace shape: {r['pace_shape']} (early types: {r['num_early']}" + (f", lone speed #{r['lone_speed']}" if r["lone_speed"] else "") + ")")
        names = {s["pgm"]: s for s in r["sheets"]}
        L.append(f"**PLAY: {', '.join('#' + p + ' ' + names[p]['name'] + ' (' + str(names[p]['ml_odds']) + ')' for p in r['picks'])}**  — {r['bet_structure']}")
        L.append(f"Confidence: {r['confidence']} — {r['selection_note']}")
        L.append("")
        L.append("| Rk | # | Horse | ML | Style/pts | PP | Score | Win % | Fair / min | Value | Top reasons |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for s in r["sheets"]:
            hits = sorted([h for h in s["hits"] if h["points"] and not h.get("value")], key=lambda h: -abs(h["points"]))
            top = "; ".join(f"{h['rule']} {h['points']:+.1f} {h['note'][:60]}" for h in hits[:4 if detail else 2])
            elim = " **ELIM**" if s["eliminated"] else ""
            flag = (" [" + "; ".join(s["flags"]) + "]") if s["flags"] else ""
            L.append(f"| {s['rank']} | {s['pgm']} | {s['name']}{elim}{flag} | {s['ml_odds']} | {s['run_style']}/{s['speed_pts']} | {s['prime_power']} | {s['score']:.1f} | {s['win_prob']:.0%} | {s['fair_odds']}{'' if s.get('min_win_odds') is None else ' / ' + format(s['min_win_odds'], 'g')} | {value_text(s)} | {top} |")
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
