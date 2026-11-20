"""Racing Dudes and Timeform scored on money, bet type by bet type, beside the engine on the same races.

Racing Dudes publish tickets; they are settled as published:
  WIN, PLACE and SHOW at $2 on their Win pick;
  EXACTA, TRIFECTA (and SUPERFECTA when printed) from their wager lines: "2,3,7 BOX" is a box, "2,3/2,3,4" a part-wheel;
  DOUBLE, PICK 3 and PICK 4 built from their Multi Race horses in consecutive races (built by us from their legs).
Timeform publishes picks but no tickets, so its Power Picks are put into the engine's structures (built by us):
  WIN on Power Pick 1; EXACTA box of Power Picks 1-2; TRIFECTA box of Power Picks 1-3.
Stakes are the configured units ($2 win / place / show, $1 exacta, $0.50 trifecta, $0.10 superfecta, $1 double,
$1 Pick 3, $0.50 Pick 4).  Scratched horses (not in the pre-race run's field) are taken out of every ticket.  Pick 3
and Pick 4 are tracked, not counted, as for the engine.  The engine is scored on exactly the races where the source
had picks (multi-race bets only when every leg is one of those races), from each card's pre-race prediction.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict

from .wagering import DEFAULT_WAGERING, evaluate_card, evaluate_wager, make_wager, unit_for

COUNTED_ORDER = ("WIN", "PLACE", "SHOW", "EXACTA", "TRIFECTA", "SUPERFECTA", "DOUBLE")
TRACKED = ("PICK3", "PICK4")
SLOTS = {"EXACTA": 2, "TRIFECTA": 3, "SUPERFECTA": 4}


def parse_ticket(text: str | None, slots: int) -> tuple[list[list[str]], bool] | None:
    """'2,3,7 BOX' -> ([[2,3,7]] * slots, True); '2,3/2,3,4' -> ([[2,3],[2,3,4]], False); anything else None."""
    if not text:
        return None
    t = text.upper().strip()
    box = "BOX" in t
    t = t.replace("BOX", " ").strip()
    parts = [[x.strip() for x in p.split(",") if x.strip()] for p in t.split("/")]
    if not parts or any(not p or not all(re.fullmatch(r"\d{1,2}[A-Z]?", x) for x in p) for p in parts):
        return None
    if box:
        return ([parts[0]] * slots, True) if len(parts) == 1 and len(parts[0]) >= slots else None
    return (parts, False) if len(parts) == slots else None


def _field(r: dict) -> set:
    return {s["pgm"].upper() for s in r.get("sheets", []) if not s.get("flags")}


def _clean(legs: list[list[str]], field: set) -> list[list[str]] | None:
    out = [[p for p in leg if p.upper() in field] for leg in legs]
    return out if all(out) else None


def rd_wagers(snap: dict) -> tuple[list[dict], set]:
    """Racing Dudes' tickets for one card's pre-race prediction, and the races they cover."""
    W, races, multi = [], set(), {}
    for r in snap.get("races", []):
        rd = r.get("racing_dudes") or {}
        order = rd.get("order") or []
        if not order:
            continue
        rn, field = r["race_no"], _field(r)
        races.add(rn)
        top = order[0] if order[0].upper() in field else None
        if top:
            for t in ("WIN", "PLACE", "SHOW"):
                W.append(make_wager(t, [[top]], False, f"Racing Dudes {t.lower()} #{top}", "racing_dudes", rn))
        for key, t in (("exacta", "EXACTA"), ("trifecta", "TRIFECTA"), ("superfecta", "SUPERFECTA")):
            tk = parse_ticket((rd.get("wagers") or {}).get(key), SLOTS[t])
            if not tk:
                continue
            legs = _clean(tk[0], field)
            if legs and (not tk[1] or len(legs[0]) >= SLOTS[t]):
                w = make_wager(t, [legs[0]] * SLOTS[t] if tk[1] else legs, tk[1], f"Racing Dudes {t.lower()} {(rd.get('wagers') or {}).get(key)}", "racing_dudes", rn)
                if w["combos"]:
                    W.append(w)
        ml = (rd.get("wagers") or {}).get("multi_race")
        if ml:
            legs = _clean([[x.strip() for x in ml.split(",") if x.strip()]], field)
            if legs:
                multi[rn] = legs[0]
    for rn in sorted(multi):
        for t, n in (("DOUBLE", 2), ("PICK3", 3), ("PICK4", 4)):
            seq = list(range(rn, rn + n))
            if all(x in multi for x in seq):
                W.append(make_wager(t, [multi[x] for x in seq], False, f"Racing Dudes {t.lower()} R{seq[0]}-R{seq[-1]} (built from their Multi Race horses)",
                                    "racing_dudes", seq[-1], seq))
    return W, races


def tf_wagers(snap: dict) -> tuple[list[dict], set]:
    """Timeform's Power Picks in the engine's structures (built by us; Timeform publishes no tickets)."""
    W, races = [], set()
    for r in snap.get("races", []):
        pp = [p for p in ((r.get("timeform") or {}).get("power_picks") or []) if p.upper() in _field(r)]
        if not pp:
            continue
        rn = r["race_no"]
        races.add(rn)
        W.append(make_wager("WIN", [[pp[0]]], False, f"Timeform win #{pp[0]} (Power Pick 1)", "timeform", rn))
        if len(pp) >= 2:
            W.append(make_wager("EXACTA", [pp[:2], pp[:2]], True, f"Timeform exacta box #{pp[0]}-#{pp[1]}", "timeform", rn))
        if len(pp) >= 3 and len(_field(r)) >= 5:
            W.append(make_wager("TRIFECTA", [pp[:3]] * 3, True, f"Timeform trifecta box #{'-#'.join(pp[:3])}", "timeform", rn))
    return W, races


def _agg(rows: list[dict]) -> dict:
    by = defaultdict(lambda: {"bets": 0, "won": 0, "unknown": 0, "not_offered": 0, "cost": 0.0, "ret": 0.0})
    for x in rows:
        d = by[x["type"]]
        if not x.get("placed", True):
            d["not_offered"] += 1
            continue
        d["bets"] += 1
        if not x["known"]:
            d["unknown"] += 1
            continue
        d["won"] += int(x["hit"]); d["cost"] += x["cost"]; d["ret"] += x["ret"] or 0.0
    out = {}
    for t, d in by.items():
        d["cost"], d["ret"] = round(d["cost"], 2), round(d["ret"], 2)
        d["roi"] = round((d["ret"] - d["cost"]) / d["cost"], 3) if d["cost"] else None
        out[t] = d
    return out


def _total(by: dict, types) -> dict:
    t = {"bets": 0, "won": 0, "cost": 0.0, "ret": 0.0}
    for k in types:
        d = by.get(k)
        if d:
            t["bets"] += d["bets"]; t["won"] += d["won"]; t["cost"] += d["cost"]; t["ret"] += d["ret"]
    t["cost"], t["ret"] = round(t["cost"], 2), round(t["ret"], 2)
    t["roi"] = round((t["ret"] - t["cost"]) / t["cost"], 3) if t["cost"] else None
    return t


def compare(root: str, cfg: dict) -> dict:
    from .results import load_results
    from .snapshot import pre_race_by_race
    wcfg = dict(DEFAULT_WAGERING, **(cfg.get("wagering") or {}))
    out_dir, res_dir = os.path.join(root, "data", "out"), os.path.join(root, "results")
    acc = {"racing_dudes": {"rows": [], "engine": [], "races": 0, "cards": set()}, "timeform": {"rows": [], "engine": [], "races": 0, "cards": set()}}
    if os.path.isdir(res_dir):
        for rp in sorted(os.listdir(res_dir)):
            if not rp.endswith(".results.json"):
                continue
            card = rp.split(".")[0]
            if not os.path.isdir(os.path.join(out_dir, "snapshots", card)):
                continue
            res = load_results(os.path.join(res_dir, rp))
            by_no = {x["race_no"]: x for x in res.get("races", [])}
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
            done = {rn for rn, x in by_no.items() if x.get("finish")}
            try:
                eng = evaluate_card(snap, res, wcfg)["rows"]
            except ValueError:            # results for another card: never scored
                continue
            for key, fn in (("racing_dudes", rd_wagers), ("timeform", tf_wagers)):
                W, races = fn(snap)
                races &= done
                if not races:
                    continue
                a = acc[key]
                a["races"] += len(races); a["cards"].add(card)
                for w in W:
                    if not set(w["races"]) <= races:
                        continue
                    a["rows"].append(dict(evaluate_wager(w, by_no, unit_for(w, wcfg)), type=w["type"], label=w["label"], card=card, races=w["races"]))
                a["engine"] += [dict(x, card=card) for x in eng if set(x["races"]) <= races]
    out = {"note": "Racing Dudes' tickets as published (doubles and Pick 3/4 built from their Multi Race horses); Timeform's Power Picks in "
                   "the engine's structures (built by us); the engine on exactly the same races, from each card's pre-race prediction. "
                   "Pick 3 and Pick 4 are tracked, not counted.", "sources": {}}
    for key, a in acc.items():
        src = _agg(a["rows"])
        engine_rows = [x for x in a["engine"] if x.get("placed", True) or x.get("status") == "not offered"]
        eng = _agg(engine_rows)
        out["sources"][key] = {"races": a["races"], "cards": len(a["cards"]),
                               "by_type": src, "engine_by_type": eng,
                               "total": _total(src, COUNTED_ORDER), "engine_total": _total(eng, COUNTED_ORDER),
                               "tracked": _total(src, TRACKED), "engine_tracked": _total(eng, TRACKED)}
    return out


def format_compare(c: dict) -> str:
    names = {"racing_dudes": "Racing Dudes", "timeform": "Timeform"}
    L = ["# Picks sources against the engine, by bet type", "", c["note"], ""]
    for key, s in c["sources"].items():
        L.append(f"## {names[key]}: {s['races']} races on {s['cards']} cards")
        if not s["races"]:
            L.append(""); L.append("No races yet with this source's picks in the pre-race run and a result."); L.append("")
            continue
        L += ["", "| Bet | Source bets | Won | Cost | Return | Result | Engine bets | Won | Cost | Return | Result |", "|---|---|---|---|---|---|---|---|---|---|---|"]

        def cells(d):
            return f"{d['bets']} | {d['won']} | ${d['cost']:.2f} | ${d['ret']:.2f} | " + (f"{d['roi']:+.1%}" if d.get("roi") is not None else "")
        empty = {"bets": 0, "won": 0, "cost": 0.0, "ret": 0.0, "roi": None}
        for t in COUNTED_ORDER + TRACKED:
            a, b = s["by_type"].get(t), s["engine_by_type"].get(t)
            if a or b:
                L.append(f"| {t.title() if t not in TRACKED else t.replace('PICK', 'Pick ')}{' (tracked)' if t in TRACKED else ''} | {cells(a or empty)} | {cells(b or empty)} |")
        L.append(f"| **Counted total** | {cells(s['total'])} | {cells(s['engine_total'])} |")
        L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    import sys
    from .engine import load_config
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    print(format_compare(compare(root, load_config(os.path.join(root, "rules_config.json")))))
