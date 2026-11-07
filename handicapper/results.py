"""
Race results, scratches and same-day bias.

Results file (results/<card>.results.json), transcribed from the track's
payout / finish-order pages:

{
  "track": "Del Mar", "date": "2026-11-06",
  "races": [
    {"race_no": 1,
     "finish": ["1", "6", "4", "3"],                 # program numbers, 1st .. nth (as many as known)
     "win": 5.20, "place": {"1": 3.40, "6": 9.20}, "show": {"1": 2.10, "6": 3.20, "4": 2.10},   # $2 payoffs
     "exotics": [{"type": "EXACTA", "base": 1.0, "combo": "1/6", "payout": 17.30}, ...],
     "final_odds": {"1": 1.6, "6": 9.4}             # optional, decimal odds-to-1 when the chart shows them
    }
  ]
}

Scratch spec (pick.py --scratch): "3:3, 4:6, 8:4, 8:9"  -> race 3 program 3, race 4 program 6, race 8 programs 4 and 9.
"""
from __future__ import annotations

import json
import re

EARLY = ("E", "E/P")
LATE = ("P", "S")


def load_results(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        res = json.load(fh)
    for r in res.get("races", []):
        r["finish"] = [str(p) for p in r.get("finish", [])]
    return res


# ---------------------------------------------------------------------------
# Scratches
# ---------------------------------------------------------------------------
def parse_scratch_spec(spec: str | None) -> dict[int, list[str]]:
    """'3:3, 4:6 8:4,8:9' -> {3: ['3'], 4: ['6'], 8: ['4', '9']}."""
    out: dict[int, list[str]] = {}
    for tok in re.split(r"[,\s]+", (spec or "").strip()):
        if not tok:
            continue
        m = re.fullmatch(r"(\d+):(\d+[A-Za-z]?)", tok)
        if not m:
            raise ValueError(f"bad scratch token {tok!r}; expected race:program like 8:4")
        out.setdefault(int(m.group(1)), []).append(m.group(2).upper())
    return out


def apply_scratches(card: dict, scratches: dict[int, list[str]]) -> list[str]:
    """Remove scratched horses from the card in place.  For every scratch in a race, the lowest-numbered
    also-eligible (AE) in that race draws in (its entry_status is cleared) - the track's draw-in order.
    Main-track-only (MTO) horses are left flagged: they run only if the race comes off the turf.
    Returns human-readable notes."""
    notes = []
    for race in card["races"]:
        pg = scratches.get(race["race_no"], [])
        if not pg:
            continue
        before = len(race["horses"])
        gone = [h for h in race["horses"] if h["pgm"].upper() in pg]
        race["horses"] = [h for h in race["horses"] if h["pgm"].upper() not in pg]
        missing = [p for p in pg if p not in {h["pgm"].upper() for h in gone}]
        for p in missing:
            notes.append(f"R{race['race_no']}: program {p} not found (already absent?)")
        for h in gone:
            notes.append(f"R{race['race_no']}: scratched #{h['pgm']} {h['name']}")
        body_scratches = sum(1 for h in gone if h.get("entry_status") != "AE")   # a scratched AE draws nobody in
        aes = sorted((h for h in race["horses"] if h.get("entry_status") == "AE"), key=lambda h: _pgm_key(h["pgm"]))
        for h in aes[:body_scratches]:
            h["entry_status"] = None
            notes.append(f"R{race['race_no']}: #{h['pgm']} {h['name']} draws in from the also-eligible list")
        race["field_size"] = len(race["horses"])
        if race.get("summary"):
            race["summary"] = [e for e in race["summary"] if str(e.get("pgm", "")).upper() not in pg]
        if before and not race["horses"]:
            notes.append(f"R{race['race_no']}: no horses left")
    return notes


def _pgm_key(p: str):
    m = re.match(r"(\d+)([A-Za-z]?)", p)
    return (int(m.group(1)), m.group(2)) if m else (999, p)


# ---------------------------------------------------------------------------
# Same-day bias from the results of earlier races on the card
# ---------------------------------------------------------------------------
def attach_day_bias(card: dict, results: dict) -> list[str]:
    """For each race, summarise the winners of the *earlier* races on the same surface today: how many were
    early types (E, E/P) vs late (P, S), and how many came from inside (post 1-3) / middle / outside (8+) posts.
    Stored as race['day_bias'] and read by rule P10.  Needs the winner's run style and post, which are looked
    up in the card itself (the winner must be among the parsed horses)."""
    by_no = {r["race_no"]: r for r in results.get("races", [])}
    done = []
    notes = []
    for race in card["races"]:
        same = [d for d in done if d["surface"] == race["surface"]]
        race["day_bias"] = {
            "n": len(same),
            "early_wins": sum(1 for d in same if d["run_style"] in EARLY),
            "late_wins": sum(1 for d in same if d["run_style"] in LATE),
            "inside_wins": sum(1 for d in same if d["post"] is not None and d["post"] <= 3),
            "outside_wins": sum(1 for d in same if d["post"] is not None and d["post"] >= 8),
            "winners": [f"R{d['race_no']} #{d['pgm']} {d['run_style']} post {d['post']}" for d in same],
        }
        res = by_no.get(race["race_no"])
        if res and res.get("finish"):
            wpgm = res["finish"][0]
            w = next((h for h in race["horses"] if h["pgm"].upper() == wpgm.upper()), None)
            if w:
                done.append({"race_no": race["race_no"], "surface": race["surface"], "pgm": wpgm,
                             "run_style": w.get("run_style"), "post": w.get("post")})
            else:
                notes.append(f"R{race['race_no']}: winner #{wpgm} not among parsed horses; not used for day bias")
    return notes


# ---------------------------------------------------------------------------
# Back-test join
# ---------------------------------------------------------------------------
def backtest(picks: dict, results: dict, stake: float = 2.0) -> dict:
    """Join a picks.json with a results file.  Reports, per race, where the winner was ranked, whether the
    primary play won and what a flat win bet on the top pick returned, whether the top three covered the
    winner; per rule, how often a horse that triggered it positively / negatively won; and whether the
    recommended Pick 3 / Pick 4 tickets would have hit (payoff only if the results file carries it)."""
    by_no = {r["race_no"]: r for r in results.get("races", [])}
    races_out, rule_stats = [], {}
    bet, ret = 0.0, 0.0
    for r in picks["races"]:
        res = by_no.get(r["race_no"])
        if not res or not res.get("finish"):
            continue
        win = res["finish"][0]
        sheets = {s["pgm"]: s for s in r["sheets"]}
        wsheet = sheets.get(win)
        live = [s for s in r["sheets"] if not s["eliminated"] and not s["flags"]]
        top = live[0]["pgm"] if live else None
        row = {"race_no": r["race_no"], "winner": win, "winner_rank": wsheet["rank"] if wsheet else None,
               "winner_eliminated": bool(wsheet and wsheet["eliminated"]), "top_pick": top,
               "top_pick_won": top == win, "winner_in_top3": win in [s["pgm"] for s in live[:3]],
               "picks_hit": win in r["picks"], "win_payoff": res.get("win")}
        if top:
            bet += stake
            if top == win and res.get("win"):
                ret += res["win"] * stake / 2.0
        races_out.append(row)
        for s in r["sheets"]:
            for h in s["hits"]:
                if not h["points"]:
                    continue
                k = (h["rule"], "pos" if h["points"] > 0 else "neg")
                st = rule_stats.setdefault(k, {"rule": h["rule"], "sign": k[1], "fired": 0, "won": 0, "itm": 0})
                st["fired"] += 1
                st["won"] += int(s["pgm"] == win)
                st["itm"] += int(s["pgm"] in res["finish"][:3])
    multi = {}
    for key in ("pick3", "pick4"):
        rec = ((picks.get("multirace") or {}).get(key) or {}).get("recommended")
        if not rec:
            continue
        winners = [by_no.get(n, {}).get("finish", [None])[0] for n in rec["races"]]
        if any(w is None for w in winners):
            multi[key] = {"name": rec["name"], "known": False}
            continue
        hit = any(all(w in leg for w, leg in zip(winners, t["legs"])) for t in rec["tickets"])
        multi[key] = {"name": rec["name"], "known": True, "winners": winners, "hit": hit, "cost": rec["cost"]}
    rules = sorted(rule_stats.values(), key=lambda x: (x["rule"], x["sign"]))
    for st in rules:
        st["win_pct"] = round(100.0 * st["won"] / st["fired"], 1)
        st["itm_pct"] = round(100.0 * st["itm"] / st["fired"], 1)
    n = len(races_out)
    return {"races": races_out, "rules": rules, "multirace": multi,
            "summary": {"races": n, "top_pick_wins": sum(r["top_pick_won"] for r in races_out),
                        "winner_in_top3": sum(r["winner_in_top3"] for r in races_out),
                        "winner_eliminated": sum(r["winner_eliminated"] for r in races_out),
                        "flat_win_bet": round(bet, 2), "flat_win_return": round(ret, 2),
                        "flat_win_roi": round((ret - bet) / bet, 3) if bet else None}}


def format_backtest(bt: dict) -> str:
    s = bt["summary"]
    L = [f"# Back-test: {s['races']} races", ""]
    L.append(f"Top pick won {s['top_pick_wins']}/{s['races']}; winner in top 3: {s['winner_in_top3']}/{s['races']}; "
             f"winner had been eliminated: {s['winner_eliminated']}; flat ${2:.0f} win on the top pick: bet ${s['flat_win_bet']:.2f}, "
             f"returned ${s['flat_win_return']:.2f}" + (f" (ROI {s['flat_win_roi']:+.1%})" if s["flat_win_roi"] is not None else ""))
    L.append("")
    L.append("| Race | Winner | Winner rank | Eliminated? | Top pick | Hit | Win $2 |")
    L.append("|---|---|---|---|---|---|---|")
    for r in bt["races"]:
        L.append(f"| {r['race_no']} | #{r['winner']} | {r['winner_rank']} | {'yes' if r['winner_eliminated'] else ''} | #{r['top_pick']} | "
                 f"{'WIN' if r['top_pick_won'] else ('top3' if r['winner_in_top3'] else '')} | {r['win_payoff'] if r['win_payoff'] is not None else ''} |")
    L.append("")
    for key, m in bt["multirace"].items():
        if m.get("known"):
            L.append(f"- {m['name']}: winners {', '.join('#' + w for w in m['winners'])} -> {'HIT' if m['hit'] else 'miss'} (cost ${m['cost']:.2f})")
        else:
            L.append(f"- {m['name']}: results incomplete")
    L.append("")
    L.append("| Rule | Sign | Fired | Won | Win% | ITM% |")
    L.append("|---|---|---|---|---|---|")
    for st in bt["rules"]:
        L.append(f"| {st['rule']} | {st['sign']} | {st['fired']} | {st['won']} | {st['win_pct']} | {st['itm_pct']} |")
    return "\n".join(L)
