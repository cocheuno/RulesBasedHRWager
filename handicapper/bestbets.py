"""Best bets of the day: one rule, used both for today's list on the Desk and for the record.

Rule: for each card, the engine's suggested WIN bets, ranked by heuristic expected value at the morning line
(EV = p * (ML + 1) - 1 with p the engine's model probability); the top two, one per horse.  A labelled view, not a
validated edge.

The record applies the same rule to each card's pre-race prediction (snapshot.pre_race_by_race: per race the newest
run made without that race's result), so re-running a card after the races cannot change its best bets.  Each bet is
settled at $2 against the chart: every best bet, and separately only those whose final odds met the engine's
minimum price (the passed-at-the-window view).
"""
from __future__ import annotations

import json
import os
from collections import defaultdict

PER_CARD = 2
STAKE = 2.0


def select(picks: dict, per_card: int = PER_CARD) -> list[dict]:
    """The best bets of one card from a picks document (a run or a pre-race composite)."""
    from .research import ev
    cands = []
    for r in picks.get("races", []):
        names = {s["pgm"]: s for s in r.get("sheets", [])}
        for w in r.get("wagers", []):
            if w.get("type") != "WIN":
                continue
            for pgm in w["legs"][0]:
                s = names.get(pgm)
                if not s or s.get("ml_decimal") is None or not s.get("model_prob"):
                    continue
                cands.append({"race_no": r["race_no"], "pgm": pgm, "name": s.get("name"), "ml_odds": s.get("ml_odds"),
                              "min_odds": (w.get("min_odds_by") or {}).get(pgm, w.get("min_odds")), "win_prob": s.get("win_prob"),
                              "model_prob": s.get("model_prob"), "ev_at_ml": ev(s["model_prob"], s["ml_decimal"]), "confidence": r.get("confidence"),
                              "post_time": r.get("post_time"), "surface": r.get("surface"), "label": w.get("label"),
                              "decision_id": (w.get("decision") or {}).get("id")})
    seen, top = set(), []
    for x in sorted(cands, key=lambda z: (-(z["ev_at_ml"] if z["ev_at_ml"] is not None else -9), z["race_no"], z["pgm"])):
        if (x["race_no"], x["pgm"]) in seen:
            continue
        seen.add((x["race_no"], x["pgm"])); top.append(x)
        if len(top) == per_card:
            break
    return top


def _totals(rows: list[dict]) -> dict:
    n = len(rows)
    bet = STAKE * n
    ret = sum(r["return"] for r in rows)
    return {"bets": n, "won": sum(r["won"] for r in rows), "itm": sum(r["itm"] for r in rows), "cost": round(bet, 2),
            "return": round(ret, 2), "roi": round((ret - bet) / bet, 3) if bet else None}


def record(root: str, cfg: dict) -> dict:
    """Every best bet on file, settled against the charts, with totals overall, at the price, by track, by date."""
    from .results import load_results
    from .snapshot import pre_race_by_race
    out_dir, res_dir = os.path.join(root, "data", "out"), os.path.join(root, "results")
    rows = []
    if os.path.isdir(res_dir):
        for rp in sorted(os.listdir(res_dir)):
            if not rp.endswith(".results.json"):
                continue
            card = rp.split(".")[0]
            if not os.path.isdir(os.path.join(out_dir, "snapshots", card)):
                continue
            res = load_results(os.path.join(res_dir, rp))
            by = {x["race_no"]: x for x in res.get("races", [])}
            code = None
            try:
                with open(os.path.join(out_dir, f"{card}.picks.json"), encoding="utf-8") as fh:
                    code = json.load(fh).get("track_code")
            except (OSError, ValueError):
                pass
            snap = pre_race_by_race(out_dir, card, res, ((cfg.get("tracks") or {}).get(code or "") or {}).get("timezone"),
                                    (cfg.get("timing") or {}).get("cutoff_margin_minutes", 2))
            if not snap:
                continue
            try:
                from .results import check_identity
                check_identity(snap, res)
            except ValueError:                  # another card's results: never scored
                continue
            code = snap.get("track_code") or code
            for b in select(snap):
                x = by.get(b["race_no"])
                if not x or not x.get("finish"):
                    continue
                fo = (x.get("final_odds") or {}).get(b["pgm"])
                from .results import win_price_of, winners_of
                won = b["pgm"] in winners_of(x)                     # a dead heat for the win counts each winner
                pay = (win_price_of(x, b["pgm"]) or 0.0) if won else 0.0
                rows.append(dict(b, card=card, track=code, date=snap.get("date"), winner=winners_of(x)[0], won=won,
                                 itm=b["pgm"] in x["finish"][:3], final_odds=fo, win_payoff=win_price_of(x, b["pgm"]) if won else None,
                                 **{"return": round(STAKE * pay / 2.0, 2)},
                                 price_met=None if fo is None or b["min_odds"] is None else fo >= b["min_odds"]))
    rows.sort(key=lambda r: (r["date"] or "", r["card"], r["race_no"]))
    at_price = [r for r in rows if r["price_met"] is not False]
    by_track, by_date = defaultdict(list), defaultdict(list)
    for r in rows:
        by_track[r["track"]].append(r); by_date[r["date"]].append(r)
    return {"rule": f"the engine's suggested win bets ranked by expected value at the morning line, top {PER_CARD} per card; "
                    "taken from each card's pre-race prediction, settled at $2 against the chart",
            "label": "a labelled view, not a validated edge",
            "all": _totals(rows), "at_price": _totals(at_price),
            "passed_winners": sum(1 for r in rows if r["won"] and r["price_met"] is False),
            "by_track": {k: _totals(v) for k, v in sorted(by_track.items())},
            "by_date": {k: _totals(v) for k, v in sorted(by_date.items())},
            "cards": len({r["card"] for r in rows}), "first_date": rows[0]["date"] if rows else None, "last_date": rows[-1]["date"] if rows else None,
            "rows": rows}


def summary_line(rec: dict) -> str:
    a = rec["all"]
    if not a["bets"]:
        return "No best bets with results on file yet."
    return (f"So far {a['won']} of {a['bets']} won ({a['roi']:+.0%} at $2) over {rec['cards']} cards, {rec['first_date']} to {rec['last_date']}; "
            f"only where the final odds met the minimum price: {rec['at_price']['won']} of {rec['at_price']['bets']} ({rec['at_price']['roi']:+.0%})"
            if rec["at_price"]["roi"] is not None else f"So far {a['won']} of {a['bets']} won ({a['roi']:+.0%} at $2).")


def format_record(rec: dict) -> str:
    L = [f"# Best bets of the day: record", "", f"Rule: {rec['rule']}. {rec['label'].capitalize()}.", "", summary_line(rec), "",
         "| By | Bets | Won | In the money | Cost | Return | Result |", "|---|---|---|---|---|---|---|"]
    for name, t in [("All", rec["all"]), ("Final odds met the minimum", rec["at_price"])] + [(k, v) for k, v in rec["by_track"].items()] + [(k, v) for k, v in rec["by_date"].items()]:
        L.append(f"| {name} | {t['bets']} | {t['won']} | {t['itm']} | ${t['cost']:.2f} | ${t['return']:.2f} | {t['roi']:+.1%} |" if t["roi"] is not None else f"| {name} | 0 | | | | | |")
    return "\n".join(L)


if __name__ == "__main__":
    import sys
    from .engine import load_config
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    print(format_record(record(root, load_config(os.path.join(root, "rules_config.json")))))
