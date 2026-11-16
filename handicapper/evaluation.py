"""Prospective evaluation and the data watch (Phase E).

Measures the pre-race predictions on file against the charts, honestly:
  * the unit is a race, never a bet; every count below is races;
  * a race enters only through the composite pre-race prediction (snapshot.pre_race_by_race): the newest run
    made without that race's result, whatever the hour (the owner's rule: the clock is a label);
  * three vectors are compared on the same races: the public baseline (the morning line renormalised), the rule
    heuristic (softmax of the ability score) and the blend the engine prints (win_prob); the chart's final odds
    renormalised are shown too, labelled hindsight, because they are not available before the race;
  * candidate blends (the morning-line weight on a grid) are *looked at* on the earlier half of the races by
    date and *reported* on the later half; nothing is fitted on the races it is scored on, and nothing is
    written back to the configuration;
  * metrics: multiclass log loss with a documented floor, Brier score, reliability bins with counts, by field
    size, track, surface, condition and pace shape; the mean absolute gap between a prediction and the final-odds
    market; coverage and freshness; bootstrap confidence intervals over races.

The data watch counts the races on file against the gates in rules_config.json -> data_watch (thresholds the owner
sets; the code only counts).  Until a gate is met its capability is DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA.
"""
from __future__ import annotations

import glob
import json
import math
import os
import random
from collections import defaultdict
from datetime import datetime, timezone

DEFAULT_DATA_WATCH = {
    "floor": 0.001,                        # probability floor in the log loss (every vector, every horse), documented
    "bootstrap": 1000,
    "seed": 2026,
    "blend_grid": [0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0],
    "gates": {
        "global_calibration": {"threshold": 300, "unit": "races with a pre-race prediction and a chart result",
                               "capability": "calibration pass of the softmax scale and the morning-line blend (global)"},
        "track_specific": {"threshold": 400, "unit": "races at one track with a pre-race prediction and a result",
                           "capability": "anything track-specific (weights, scale, blend per track)"},
        "odds_drift": {"threshold": 150, "unit": "races with a complete tote history (final board with history stored)",
                       "capability": "late-odds drift forecast"},
        "timeform_value": {"threshold": 200, "unit": "races with both Brisnet and Timeform figures and a result",
                           "capability": "Timeform's incremental value"},
    },
}
DEFERRED = "DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA"
READY = "GATE_MET_AWAITING_OWNER_REVIEW"
HINDSIGHT = "final-odds market (hindsight: not available before the race)"


# ---------------------------------------------------------------------------
# Collect the race records
# ---------------------------------------------------------------------------
def _norm(v: dict) -> dict:
    z = sum(x for x in v.values() if x)
    return {k: (x or 0.0) / z for k, x in v.items()} if z > 0 else {}


def race_records(root: str, cfg: dict, cards: list[str] | None = None) -> list[dict]:
    """One record per race with a pre-race prediction and a chart result (winner among the running horses)."""
    from handicapper.results import load_results
    from handicapper.snapshot import pre_race_by_race
    out_dir, res_dir = os.path.join(root, "data", "out"), os.path.join(root, "results")
    tracks = cfg.get("tracks") or {}
    margin = (cfg.get("timing") or {}).get("cutoff_margin_minutes", 2)
    tote = _tote_history_races(root)
    recs = []
    cards = cards or sorted(os.path.basename(p).split(".")[0] for p in glob.glob(os.path.join(res_dir, "*.results.json")))
    for card in cards:
        rp = os.path.join(res_dir, f"{card}.results.json")
        if not os.path.exists(rp) or not os.path.isdir(os.path.join(out_dir, "snapshots", card)):
            continue
        res = load_results(rp)
        code = None
        try:
            with open(os.path.join(out_dir, f"{card}.picks.json"), encoding="utf-8") as fh:
                code = json.load(fh).get("track_code")
        except (OSError, ValueError):
            pass
        snap = pre_race_by_race(out_dir, card, res, (tracks.get(code or "") or {}).get("timezone"), margin)
        if not snap:
            continue
        code = snap.get("track_code") or code or (card[:3].upper())
        by_no = {r["race_no"]: r for r in res.get("races", [])}
        per_race = (snap.get("timing") or {}).get("per_race") or {}
        for r in snap["races"]:
            x = by_no.get(r["race_no"])
            if not x or not x.get("finish"):
                continue
            running = [s for s in r["sheets"] if not s.get("flags")]
            winner = x["finish"][0]
            if winner not in {s["pgm"] for s in running}:
                continue
            model = {s["pgm"]: s.get("model_prob") or 0.0 for s in running}
            market = {s["pgm"]: (s.get("market_prob") if s.get("market_prob") is not None else None) for s in running}
            blend = {s["pgm"]: s.get("win_prob") or 0.0 for s in running}
            fo = x.get("final_odds") or {}
            final = _norm({s["pgm"]: (1.0 / (fo[s["pgm"]] + 1.0) if fo.get(s["pgm"]) is not None else 0.0) for s in running}) if fo else None
            has_tf = sum(1 for s in running if (s.get("timeform") or {}).get("top_fig") is not None) >= max(2, len(running) // 2)
            pr = per_race.get(str(r["race_no"])) or {}
            live = [s for s in running if not s.get("eliminated")]
            recs.append({"card": card, "track": code, "date": snap.get("date"), "race_no": r["race_no"], "winner": winner,
                         "field_size": len(running), "live": len(live), "surface": (r.get("surface") or "").lower() or None,
                         "condition": (x.get("track_condition") or "").split(" ")[0].lower() or None, "pace_shape": r.get("pace_shape"),
                         "confidence": r.get("confidence"), "clock": pr.get("status", "unknown"), "predicted_at_utc": pr.get("at_utc"),
                         "model": _norm(model), "market": _norm(market) if all(v is not None for v in market.values()) and market else None,
                         "blend": _norm(blend), "final_market": final or None, "has_final_odds": bool(final),
                         "has_timeform": has_tf, "has_tote_history": (code, snap.get("date"), r["race_no"]) in tote,
                         "top_pick": (live[0]["pgm"] if live else None), "top_pick_won": bool(live) and live[0]["pgm"] == winner})
    recs.sort(key=lambda z: (z["date"] or "", z["card"], z["race_no"]))
    return recs


def _tote_history_races(root: str) -> set:
    """(track, date, race_no) of every race whose final tote board with history is in the ledger."""
    p = os.path.join(root, "data", "private", "carovex.db")
    if not os.path.exists(p):
        return set()
    try:
        import sqlite3
        con = sqlite3.connect(p)
        rows = con.execute("SELECT race_id, payload FROM source_observation WHERE provider='puntersedge/tvg'").fetchall()
    except Exception:
        return set()
    out = set()
    for rid, payload in rows:
        try:
            b = json.loads(payload)
        except ValueError:
            continue
        if b.get("kind") == "final" and b.get("history"):
            t, d, n = rid.split("|")
            out.add((t, d, int(n)))
    return out


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def log_loss(vec: dict, winner: str, floor: float) -> float:
    """-log p(winner) after flooring every probability at `floor` and renormalising."""
    v = {k: max(float(x), floor) for k, x in vec.items()}
    z = sum(v.values())
    return -math.log(v.get(winner, floor) / z)


def brier(vec: dict, winner: str) -> float:
    return sum((float(p) - (1.0 if k == winner else 0.0)) ** 2 for k, p in vec.items())


def metrics(recs: list[dict], key: str, floor: float) -> dict | None:
    rows = [r for r in recs if r.get(key)]
    if not rows:
        return None
    ll = [log_loss(r[key], r["winner"], floor) for r in rows]
    br = [brier(r[key], r["winner"]) for r in rows]
    top = [max(r[key], key=r[key].get) == r["winner"] for r in rows]
    return {"races": len(rows), "log_loss": round(sum(ll) / len(ll), 4), "brier": round(sum(br) / len(br), 4),
            "top_prob_hit_rate": round(sum(top) / len(top), 4), "top_prob_hits": sum(top),
            "uniform_log_loss": round(sum(math.log(len(r[key])) for r in rows) / len(rows), 4)}


def reliability(recs: list[dict], key: str, bins=(0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.6, 1.0001)) -> list[dict]:
    """Every horse's predicted probability binned; count, mean prediction and observed win rate per bin."""
    g = defaultdict(lambda: {"n": 0, "sum_p": 0.0, "wins": 0})
    for r in recs:
        v = r.get(key)
        if not v:
            continue
        for k, p in v.items():
            i = next(j for j in range(len(bins) - 1) if bins[j] <= p < bins[j + 1])
            d = g[i]; d["n"] += 1; d["sum_p"] += p; d["wins"] += int(k == r["winner"])
    out = []
    for i in range(len(bins) - 1):
        d = g.get(i)
        if not d:
            continue
        out.append({"bin": f"{bins[i]:.2f}-{min(bins[i + 1], 1.0):.2f}", "horses": d["n"], "mean_predicted": round(d["sum_p"] / d["n"], 4),
                    "observed": round(d["wins"] / d["n"], 4), "wins": d["wins"]})
    return out


def by_group(recs: list[dict], key: str, group: str, floor: float) -> list[dict]:
    g = defaultdict(list)
    for r in recs:
        if r.get(key):
            g[str(r.get(group) if r.get(group) is not None else "?")].append(r)
    rows = []
    for name, rs in sorted(g.items(), key=lambda kv: -len(kv[1])):
        m = metrics(rs, key, floor)
        rows.append({group: name, **m})
    return rows


def field_bucket(n: int) -> str:
    return "<=5" if n <= 5 else ("6-7" if n <= 7 else ("8-9" if n <= 9 else "10+"))


def market_gap(recs: list[dict], key: str) -> dict | None:
    """Mean absolute difference between the prediction and the final-odds market, per horse, over races with odds."""
    rows = [r for r in recs if r.get(key) and r.get("final_market")]
    if not rows:
        return None
    diffs = [abs(r[key].get(k, 0.0) - q) for r in rows for k, q in r["final_market"].items()]
    return {"races": len(rows), "horses": len(diffs), "mean_abs_gap": round(sum(diffs) / len(diffs), 4)}


def bootstrap_ci(recs: list[dict], key: str, floor: float, n: int, seed: int) -> dict | None:
    rows = [r for r in recs if r.get(key)]
    if len(rows) < 5:
        return None
    rnd = random.Random(seed)
    ll_s, hit_s = [], []
    pre_ll = [log_loss(r[key], r["winner"], floor) for r in rows]
    pre_hit = [1.0 if max(r[key], key=r[key].get) == r["winner"] else 0.0 for r in rows]
    m = len(rows)
    for _ in range(n):
        idx = [rnd.randrange(m) for _ in range(m)]
        ll_s.append(sum(pre_ll[i] for i in idx) / m); hit_s.append(sum(pre_hit[i] for i in idx) / m)
    ll_s.sort(); hit_s.sort()
    lo, hi = int(0.025 * n), min(n - 1, int(0.975 * n))
    return {"log_loss_95": [round(ll_s[lo], 4), round(ll_s[hi], 4)], "top_hit_95": [round(hit_s[lo], 4), round(hit_s[hi], 4)], "resamples": n}


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(c - h, 4), round(c + h, 4)]


def blend_vector(model: dict, market: dict | None, lam: float) -> dict:
    if not market:
        return dict(model)
    return {k: (1 - lam) * model.get(k, 0.0) + lam * market.get(k, 0.0) for k in model}


def candidate_blends(recs: list[dict], grid, floor: float) -> dict:
    """Chronological split: the earlier half of the races (by date) is where a blend weight would be chosen, the
    later half is where it is reported.  Both halves are shown; nothing is fitted on the reporting half."""
    rows = [r for r in recs if r.get("model") and r.get("market")]
    if len(rows) < 10:
        return {"races": len(rows), "note": "fewer than 10 races with both a model and a morning-line market", "rows": []}
    rows.sort(key=lambda r: (r["date"] or "", r["card"], r["race_no"]))
    cut = len(rows) // 2
    early, late = rows[:cut], rows[cut:]
    out = []
    for lam in grid:
        e = [log_loss(blend_vector(r["model"], r["market"], lam), r["winner"], floor) for r in early]
        l = [log_loss(blend_vector(r["model"], r["market"], lam), r["winner"], floor) for r in late]
        out.append({"ml_weight": lam, "early_log_loss": round(sum(e) / len(e), 4), "late_log_loss": round(sum(l) / len(l), 4)})
    best_early = min(out, key=lambda x: x["early_log_loss"])
    return {"races": len(rows), "early_races": len(early), "late_races": len(late), "split_date": late[0]["date"],
            "rows": out, "chosen_on_early": best_early["ml_weight"],
            "reported_on_late": next(x["late_log_loss"] for x in out if x["ml_weight"] == best_early["ml_weight"]),
            "note": "research diagnostic: a weight chosen on the early half and reported on the late half; the configuration is not changed"}


# ---------------------------------------------------------------------------
# Data watch
# ---------------------------------------------------------------------------
def data_watch(recs: list[dict], cfg: dict | None = None) -> dict:
    user = (cfg or {}).get("data_watch") or {}
    gates = {k: dict(v) for k, v in DEFAULT_DATA_WATCH["gates"].items()}      # the owner's thresholds overlay the defaults
    for k, v in (user.get("gates") or {}).items():
        gates.setdefault(k, {}).update(v or {})
    n = len(recs)
    before = sum(1 for r in recs if r["clock"] == "before-cutoff")
    per_track = defaultdict(int)
    for r in recs:
        per_track[r["track"]] += 1
    tote = sum(1 for r in recs if r["has_tote_history"])
    tf = sum(1 for r in recs if r["has_timeform"])
    counts = {"global_calibration": n, "track_specific": max(per_track.values()) if per_track else 0, "odds_drift": tote, "timeform_value": tf}
    out = {"as_of_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "races": n, "races_before_cutoff": before,
           "races_after_cutoff": sum(1 for r in recs if r["clock"] == "after-cutoff"), "per_track": dict(sorted(per_track.items())),
           "note": "counts are races with a pre-race prediction (made without the result, whatever the hour) and a chart result; "
                   "the before-cutoff subset is shown beside them", "gates": {}}
    for k, g in gates.items():
        have = counts.get(k, 0)
        thr = int(g["threshold"])
        row = {"capability": g.get("capability"), "unit": g.get("unit"), "threshold": thr, "have": have, "short_by": max(0, thr - have),
               "status": READY if have >= thr else DEFERRED}
        if k == "track_specific":
            row["per_track"] = {t: {"have": v, "status": READY if v >= thr else DEFERRED} for t, v in sorted(per_track.items())}
        out["gates"][k] = row
    return out


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------
def evaluate(root: str, cfg: dict, cards: list[str] | None = None) -> dict:
    c = dict(DEFAULT_DATA_WATCH, **((cfg or {}).get("data_watch") or {}))
    floor = float(c["floor"])
    recs = race_records(root, cfg, cards)
    vectors = (("market", "public market baseline (morning line renormalised)"), ("model", "rule heuristic (softmax of the ability score)"),
               ("blend", "engine blend as printed (win_prob)"), ("final_market", HINDSIGHT))
    comp = {}
    for key, label in vectors:
        m = metrics(recs, key, floor)
        if m:
            m |= {"label": label, "ci": bootstrap_ci(recs, key, floor, int(c["bootstrap"]), int(c["seed"])),
                  "top_hit_wilson_95": wilson(m["top_prob_hits"], m["races"]), "market_gap": market_gap(recs, key)}
        comp[key] = m
    groups = {}
    for grp in ("track", "surface", "condition", "pace_shape", "confidence", "clock"):
        groups[grp] = {k: by_group(recs, k, grp, floor) for k in ("market", "model", "blend")}
    for r in recs:
        r["field_bucket"] = field_bucket(r["field_size"])
    groups["field_size"] = {k: by_group(recs, k, "field_bucket", floor) for k in ("market", "model", "blend")}
    cards_seen = sorted({r["card"] for r in recs})
    return {"races": len(recs), "cards": len(cards_seen), "first_date": recs[0]["date"] if recs else None, "last_date": recs[-1]["date"] if recs else None,
            "floor": floor, "coverage": {"races_with_final_odds": sum(1 for r in recs if r["has_final_odds"]),
                                         "races_with_morning_line_market": sum(1 for r in recs if r["market"]),
                                         "races_before_cutoff": sum(1 for r in recs if r["clock"] == "before-cutoff"),
                                         "races_after_cutoff": sum(1 for r in recs if r["clock"] == "after-cutoff")},
            "compare": comp, "reliability": {k: reliability(recs, k) for k in ("market", "model", "blend")},
            "by": groups, "blends": candidate_blends(recs, c["blend_grid"], floor), "data_watch": data_watch(recs, cfg),
            "unit": "races", "note": "pre-race predictions only; chronological splits; nothing fitted on the races it is scored on"}


def format_watch(w: dict) -> str:
    L = [f"# Data watch (as of {w['as_of_utc']})", "",
         f"Races with a pre-race prediction and a chart result: **{w['races']}** ({w['races_before_cutoff']} made before the race's cutoff, "
         f"{w['races_after_cutoff']} after; the owner's rule: a late run is a pre-race prediction all the same).", "",
         "Per track: " + ", ".join(f"{t} {n}" for t, n in w["per_track"].items()) + ".", "",
         "| Gate | Capability | Needs | Have | Short by | Status |", "|---|---|---|---|---|---|"]
    for k, g in w["gates"].items():
        L.append(f"| {k} | {g['capability']} | {g['threshold']} {g['unit']} | {g['have']} | {g['short_by']} | `{g['status']}` |")
    if "track_specific" in w["gates"]:
        L.append("")
        L.append("Per track for the track-specific gate: " + ", ".join(f"{t} {v['have']}" for t, v in w["gates"]["track_specific"]["per_track"].items()) + ".")
    L.append("")
    L.append("Thresholds are proposals the owner can change in `rules_config.json` -> `data_watch.gates`; the code only counts. "
             "Until a gate is met its capability stays `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA`; when it is met the status becomes "
             "`GATE_MET_AWAITING_OWNER_REVIEW` and nothing is fitted until the owner says so.")
    return "\n".join(L)


def format_evaluation(ev: dict) -> str:
    L = [f"# Prospective evaluation: {ev['races']} races on {ev['cards']} cards ({ev['first_date']} to {ev['last_date']})", "",
         f"Unit: races. Probability floor in the log loss: {ev['floor']}. {ev['note']}.", "",
         "| Vector | Races | Log loss | 95% CI | Brier | Top-prob hit rate | 95% CI | Uniform log loss | Mean gap to final odds |", "|---|---|---|---|---|---|---|---|---|"]
    for k, m in ev["compare"].items():
        if not m:
            continue
        ci = m.get("ci") or {}
        gap = (m.get("market_gap") or {}).get("mean_abs_gap")
        L.append(f"| {m['label']} | {m['races']} | {m['log_loss']} | {ci.get('log_loss_95', '')} | {m['brier']} | {m['top_prob_hit_rate']:.3f} ({m['top_prob_hits']}) | "
                 f"{m.get('top_hit_wilson_95', '')} | {m['uniform_log_loss']} | {gap if gap is not None else ''} |")
    L.append("")
    L.append("## Reliability (every horse's predicted win probability, binned)")
    for k in ("market", "model", "blend"):
        L.append(""); L.append(f"**{k}**"); L.append(""); L.append("| Bin | Horses | Mean predicted | Observed | Wins |"); L.append("|---|---|---|---|---|")
        for b in ev["reliability"].get(k) or []:
            L.append(f"| {b['bin']} | {b['horses']} | {b['mean_predicted']} | {b['observed']} | {b['wins']} |")
    for grp, label in (("field_size", "field size"), ("track", "track"), ("surface", "surface"), ("condition", "condition"), ("pace_shape", "pace shape"), ("clock", "clock")):
        L.append(""); L.append(f"## By {label} (log loss; races)"); L.append("")
        L.append("| " + label + " | races | market | model | blend |"); L.append("|---|---|---|---|---|")
        rows = {r[grp if grp != "field_size" else "field_bucket"]: {} for r in ev["by"][grp]["market"]}
        for k in ("market", "model", "blend"):
            for r in ev["by"][grp][k]:
                rows.setdefault(r[grp if grp != "field_size" else "field_bucket"], {})[k] = r
        for name, d in rows.items():
            n = (d.get("model") or next(iter(d.values())))["races"]
            L.append(f"| {name} | {n} | " + " | ".join(str(d.get(k, {}).get("log_loss", "")) for k in ("market", "model", "blend")) + " |")
    b = ev["blends"]
    L.append(""); L.append("## Candidate blends (morning-line weight), chronological split"); L.append("")
    if b.get("rows"):
        L.append(f"{b['races']} races; chosen on the first {b['early_races']} (before {b['split_date']}), reported on the last {b['late_races']}. {b['note']}.")
        L.append(""); L.append("| ML weight | early log loss | late log loss |"); L.append("|---|---|---|")
        for r in b["rows"]:
            L.append(f"| {r['ml_weight']} | {r['early_log_loss']} | {r['late_log_loss']} |")
        L.append(""); L.append(f"Weight chosen on the early half: {b['chosen_on_early']} -> late-half log loss {b['reported_on_late']}. The configuration keeps its own value.")
    else:
        L.append(b.get("note", ""))
    L.append(""); L.append(format_watch(ev["data_watch"]))
    return "\n".join(L)


def main(argv=None) -> int:
    import argparse
    import sys
    from handicapper.engine import load_config
    ap = argparse.ArgumentParser(prog="python -m handicapper.evaluation", description="prospective evaluation and the data watch")
    ap.add_argument("cmd", choices=["report", "watch", "json"])
    ap.add_argument("--root", default=os.getcwd())
    ap.add_argument("--write", action="store_true", help="watch: write docs/DATA_WATCH.md; report: write docs/EVALUATION.md")
    a = ap.parse_args(argv)
    cfg = load_config(os.path.join(a.root, "rules_config.json"))
    ev = evaluate(a.root, cfg)
    if a.cmd == "json":
        print(json.dumps(ev, indent=1, default=str)); return 0
    text = format_watch(ev["data_watch"]) if a.cmd == "watch" else format_evaluation(ev)
    if a.write:
        p = os.path.join(a.root, "docs", "DATA_WATCH.md" if a.cmd == "watch" else "EVALUATION.md")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {p}", file=sys.stderr)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
