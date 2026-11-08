"""
Wagering analysis: score every suggested wager against the results file.

Policy (rules_config.json -> "wagering"):
  * a unit stake per bet type (`units`: $2 win/place/show, $1 exacta, $0.50 trifecta, $0.10 superfecta, $1 double),
    whatever the track's minimum; a recommended Pick 3 / Pick 4 ticket is priced at the denomination it was built
    at (multirace.pick3/pick4.base: $1 and $0.50, or the menu minimum when that is higher);
  * the "other wagers" count as bets placed (`count_other_wagers`), alongside the primary play and the
    recommended Pick 3 / Pick 4 tickets.

A wager is a structure the engine now emits beside its text:
  {"type": "WIN"|"EXACTA"|"TRIFECTA"|"SUPERFECTA"|"DOUBLE"|"PICK3"|"PICK4", "legs": [[pgms], ...],
   "box": bool, "combos": n, "label": "...", "source": "primary"|"other"|"multirace", "race_no": n, "races": [...]}
`combos` counts distinct outcomes covered (a key or box never pays twice for the same horse in two slots).

evaluate_card(picks, results, cfg) -> per-race rows {label, type, cost, hit, ret, known, placed, note} and totals;
  a WIN row is `placed` only when the horse's final odds (from the chart) meet the minimum price the engine asked
  for; otherwise it is "passed at the window", costs nothing and is not a bet;
rollup(evaluations) -> by bet type, by track, by confidence, plus hit/miss counts for the bar charts.
"""
from __future__ import annotations

import itertools
from collections import defaultdict

DEFAULT_UNITS = {"WIN": 2.0, "PLACE": 2.0, "SHOW": 2.0, "EXACTA": 1.0, "TRIFECTA": 0.5, "SUPERFECTA": 0.10,
                 "DOUBLE": 1.0, "PICK3": 1.0, "PICK4": 0.5}
DEFAULT_WAGERING = {"units": dict(DEFAULT_UNITS), "count_other_wagers": True}
SLOTS = {"EXACTA": 2, "TRIFECTA": 3, "SUPERFECTA": 4}


MULTI = ("DOUBLE", "PICK3", "PICK4", "PICK5", "PICK6")


def combos(legs: list[list[str]], box: bool = False, multi: bool = False) -> list[tuple]:
    """Outcomes a wager covers.  Within one race a horse cannot fill two slots, so keys and part-wheels drop
    repeats; across races (multi) every product counts because program numbers are per race.  Box: every
    ordering of n horses from the set."""
    if box:
        horses = list(dict.fromkeys(legs[0]))
        return list(itertools.permutations(horses, len(legs)))
    legs = [list(dict.fromkeys(leg)) for leg in legs]
    if multi:
        return list(itertools.product(*legs))
    return [c for c in itertools.product(*legs) if len(set(c)) == len(c)]


def make_wager(wtype: str, legs: list[list[str]], box: bool = False, label: str = "", source: str = "other",
               race_no: int | None = None, races: list[int] | None = None, unit: float | None = None) -> dict:
    """`unit` fixes the stake for this wager (a Pick 3/4 ticket's denomination); otherwise the bet type's unit
    from the wagering config applies at evaluation time."""
    legs = [[str(p) for p in leg] for leg in legs]
    n = len(combos(legs, box, wtype in MULTI))
    w = {"type": wtype, "legs": legs, "box": box, "combos": n, "label": label, "source": source,
         "race_no": race_no, "races": races or ([race_no] if race_no else [])}
    if unit is not None:
        w["unit"] = unit
    return w


def unit_for(w: dict, cfg: dict) -> float:
    """The stake per combination for one wager: its own denomination when it carries one, else the configured
    unit for its bet type ($1 when the type is not listed)."""
    if w.get("unit") is not None:
        return float(w["unit"])
    units = dict(DEFAULT_UNITS, **(cfg.get("units") or {}))
    if "unit" in cfg and "units" not in cfg:     # old single-unit config
        return float(cfg["unit"])
    return float(units.get(w["type"], 1.0))


# ---------------------------------------------------------------------------
# results lookups
# ---------------------------------------------------------------------------
def _pool(res_race: dict, wtype: str):
    for e in res_race.get("exotics", []):
        t = e["type"].upper().replace(" ", "").replace("-", "")
        if t == wtype or (wtype == "DOUBLE" and t in ("DOUBLE", "DAILYDOUBLE")):
            return e
    return None


def _per_dollar(e: dict) -> float | None:
    if e is None or e.get("payout") is None or not e.get("base"):
        return None
    return e["payout"] / e["base"]


def _combo_list(s: str) -> list[list[str]]:
    """'6,9,10/8/7/2' -> [['6','9','10'], ['8'], ['7'], ['2']] (alternates after scratches)."""
    return [[p.strip() for p in part.split(",") if p.strip()] for part in s.split("/")]


def evaluate_wager(w: dict, by_no: dict, unit: float) -> dict:
    """Return {unit, cost, hit, ret, known}.  known=False when the result or the pool payout is not on file.
    Returns are scaled to the stake: a $2 win payout x (unit / 2), an exotic's per-dollar payout x unit."""
    cost = round(w["combos"] * unit, 2)
    row = {"unit": unit, "cost": cost, "hit": False, "ret": 0.0, "known": True, "placed": True, "note": ""}
    wtype = w["type"]
    if wtype in ("WIN", "EXACTA", "TRIFECTA", "SUPERFECTA"):
        res = by_no.get(w["race_no"])
        if not res or not res.get("finish"):
            row["known"] = False
            return row
        fin = res["finish"]
        if wtype == "WIN":
            # the bet is placed only at the asked price: when the chart gives the final odds and they are under
            # the horse's minimum, the window was passed (cost 0, no hit); without final odds the ML decided
            fo = res.get("final_odds") or {}
            mins = w.get("min_odds_by") or {k: w.get("min_odds") for k in w["legs"][0]}
            placed, passed = [], []
            for k in w["legs"][0]:
                mn = mins.get(k)
                if fo.get(k) is not None and mn is not None and fo[k] < mn:
                    passed.append(f"#{k} {fo[k]:g}-1 under the {mn:g}-1 minimum")
                else:
                    placed.append(k)
            row["cost"] = round(len(placed) * unit, 2)
            row["placed"] = bool(placed)
            if passed:
                row["note"] = "passed at the window: " + "; ".join(passed)
            if not placed:
                return row
            if fin[0] in placed:
                row["hit"] = True
                row["ret"] = round(unit * (res["win"] / 2.0), 2) if res.get("win") is not None else None
                row["known"] = res.get("win") is not None
            return row
        k = SLOTS[wtype]
        if len(fin) < k:
            row["known"] = False
            return row
        actual = tuple(fin[:k])
        if actual in set(combos(w["legs"], w["box"], False)):
            row["hit"] = True
            pd = _per_dollar(_pool(res, wtype))
            row["ret"] = round(unit * pd, 2) if pd is not None else None
            row["known"] = pd is not None
        return row
    # multi-race: DOUBLE / PICK3 / PICK4
    winners = []
    for rn in w["races"]:
        res = by_no.get(rn)
        if not res or not res.get("finish"):
            row["known"] = False
            return row
        winners.append(res["finish"][0])
    if all(wn in leg for wn, leg in zip(winners, w["legs"])):
        row["hit"] = True
        last = by_no[w["races"][-1]]
        e = _pool(last, wtype)
        pd = _per_dollar(e)
        if pd is not None and e.get("combo"):
            # the pool's combo must agree with the winners we matched (alternates after scratches allowed)
            cl = _combo_list(e["combo"])
            if len(cl) == len(winners) and all(wn in part for wn, part in zip(winners, cl)):
                row["ret"] = round(unit * pd, 2)
                return row
        row["ret"], row["known"] = None, False
    return row


# ---------------------------------------------------------------------------
# card level
# ---------------------------------------------------------------------------
def _dedupe(ws: list[dict]) -> list[dict]:
    """Drop a wager whose combinations are all covered by another wager of the same type on the same race(s):
    the primary WIN and the 'other' WIN on the same horse are one bet, and an exacta box inside a part-wheel
    is already paid for.  The larger wager survives; between equals the primary play does."""
    keep = []
    for i, w in enumerate(ws):
        ci = set(combos(w["legs"], w["box"], w["type"] in MULTI))
        covered = False
        for j, v in enumerate(ws):
            if i == j or v["type"] != w["type"] or v["races"] != w["races"]:
                continue
            cj = set(combos(v["legs"], v["box"], v["type"] in MULTI))
            if ci < cj or (ci == cj and (v["source"] == "primary" and w["source"] != "primary" or (v["source"] == w["source"] and j < i))):
                covered = True
                break
        if not covered:
            keep.append(w)
    return keep


def card_wagers(picks: dict, cfg: dict) -> list[dict]:
    """Every wager the report suggested, as structures: primary plays, other wagers, recommended Pick 3 / 4,
    de-duplicated so no combination is paid for twice."""
    out = []
    for r in picks["races"]:
        ws = [w for w in r.get("wagers", []) if w["source"] != "other" or cfg.get("count_other_wagers", True)]
        for w in _dedupe(ws):
            out.append(dict(w, confidence=r["confidence"]))
    mr = picks.get("multirace") or {}
    for key, wtype in (("pick3", "PICK3"), ("pick4", "PICK4")):
        rec = (mr.get(key) or {}).get("recommended")
        if not rec:
            continue
        for t in rec["tickets"]:
            out.append(make_wager(wtype, t["legs"], False, f"{rec['name']} {t['name']}", "multirace",
                                  race_no=rec["races"][0], races=rec["races"], unit=rec.get("base")) | {"confidence": "multirace"})
    return out


def evaluate_card(picks: dict, results: dict, cfg: dict | None = None) -> dict:
    cfg = dict(DEFAULT_WAGERING, **(cfg or {}))
    by_no = {r["race_no"]: r for r in results.get("races", [])}
    rows = []
    for w in card_wagers(picks, cfg):
        ev = evaluate_wager(w, by_no, unit_for(w, cfg))
        rows.append({"race_no": w["race_no"], "races": w["races"], "type": w["type"], "label": w["label"],
                     "source": w["source"], "confidence": w.get("confidence"), **ev})
    placed = [x for x in rows if x.get("placed", True)]
    known = [x for x in placed if x["known"]]
    tot = {"bets": len(placed), "passed": len(rows) - len(placed), "known": len(known), "hits": sum(1 for x in known if x["hit"]),
           "cost": round(sum(x["cost"] for x in known), 2), "ret": round(sum(x["ret"] or 0 for x in known), 2)}
    tot["roi"] = round((tot["ret"] - tot["cost"]) / tot["cost"], 3) if tot["cost"] else None
    return {"card": picks.get("source"), "track_code": picks.get("track_code"), "date": picks.get("date"),
            "units": units_table(cfg), "rows": rows, "totals": tot}


def units_table(cfg: dict) -> dict:
    """Bet type -> unit stake, as configured (for the report header and the screen)."""
    cfg = dict(DEFAULT_WAGERING, **(cfg or {}))
    units = dict(DEFAULT_UNITS, **(cfg.get("units") or {}))
    if "unit" in cfg and "units" not in cfg:
        units = {k: float(cfg["unit"]) for k in units}
    return {k: float(v) for k, v in units.items()}


def format_units(units: dict) -> str:
    """'$2 win, $1 exacta, $0.50 trifecta, $0.10 superfecta, $1 double, $1 Pick 3, $0.50 Pick 4'."""
    names = (("WIN", "win"), ("EXACTA", "exacta"), ("TRIFECTA", "trifecta"), ("SUPERFECTA", "superfecta"),
             ("DOUBLE", "double"), ("PICK3", "Pick 3"), ("PICK4", "Pick 4"))
    def money(v):
        return f"${v:.0f}" if float(v).is_integer() else f"${v:.2f}"
    return ", ".join(f"{money(units[k])} {n}" for k, n in names if k in units)


def rollup(evaluations: list[dict]) -> dict:
    """Aggregate several cards: by bet type, by track, by confidence, and hit/miss counts per track + all."""
    def agg(keyfn):
        g = defaultdict(lambda: {"bets": 0, "passed": 0, "hits": 0, "misses": 0, "unknown": 0, "cost": 0.0, "ret": 0.0})
        for ev in evaluations:
            for x in ev["rows"]:
                k = keyfn(ev, x)
                d = g[k]
                if not x.get("placed", True):
                    d["passed"] += 1
                    continue
                d["bets"] += 1
                if not x["known"]:
                    d["unknown"] += 1
                    continue
                d["hits" if x["hit"] else "misses"] += 1
                d["cost"] += x["cost"]
                d["ret"] += x["ret"] or 0.0
        for d in g.values():
            d["cost"], d["ret"] = round(d["cost"], 2), round(d["ret"], 2)
            d["roi"] = round((d["ret"] - d["cost"]) / d["cost"], 3) if d["cost"] else None
        return dict(sorted(g.items()))
    by_track = agg(lambda ev, x: ev.get("track_code") or "?")
    out = {"by_type": agg(lambda ev, x: x["type"]), "by_track": by_track,
           "by_confidence": agg(lambda ev, x: x.get("confidence") or "?"),
           "by_track_type": agg(lambda ev, x: f"{ev.get('track_code') or '?'} {x['type']}")}
    allc = {"bets": 0, "passed": 0, "hits": 0, "misses": 0, "unknown": 0, "cost": 0.0, "ret": 0.0}
    for d in by_track.values():
        for k in ("bets", "passed", "hits", "misses", "unknown", "cost", "ret"):
            allc[k] += d[k]
    allc["cost"], allc["ret"] = round(allc["cost"], 2), round(allc["ret"], 2)
    allc["roi"] = round((allc["ret"] - allc["cost"]) / allc["cost"], 3) if allc["cost"] else None
    out["all"] = allc
    # bar-chart series: one bar pair (hits, misses) per track, plus ALL
    out["chart"] = [{"track": t, "hits": d["hits"], "misses": d["misses"]} for t, d in by_track.items()] + \
                   [{"track": "ALL", "hits": allc["hits"], "misses": allc["misses"]}]
    return out


def format_evaluation(ev: dict) -> str:
    t = ev["totals"]
    L = [f"## Wagers — {t['bets']} bets placed ({t['known']} with known results): "
         f"{t['hits']} hit, cost ${t['cost']:.2f}, returned ${t['ret']:.2f}" + (f", ROI {t['roi']:+.0%}" if t["roi"] is not None else "")
         + (f"; {t['passed']} win bet(s) passed because the final odds were under the minimum" if t.get("passed") else ""), "",
         "Unit stakes: " + format_units(ev.get("units") or DEFAULT_UNITS) + ".", ""]
    L.append("| Race | Wager | Unit | Cost | Result | Return |")
    L.append("|---|---|---|---|---|---|")
    for x in ev["rows"]:
        rn = "R" + "-".join(str(n) for n in x["races"]) if len(x["races"]) > 1 else f"R{x['race_no']}"
        res = "passed" if not x.get("placed", True) else ("HIT" if x["hit"] else ("miss" if x["known"] else "unknown"))
        ret = "" if x["ret"] is None else f"${x['ret']:.2f}"
        if x["hit"] and x["ret"] is None:
            ret = "payout not on file"
        if x.get("note"):
            ret = (ret + " " if ret else "") + f"({x['note']})"
        L.append(f"| {rn} | {x['label']} | ${x.get('unit', 1.0):.2f} | ${x['cost']:.2f} | {res} | {ret} |")
    return "\n".join(L)


def format_rollup(ru: dict) -> str:
    L = ["## Roll-up", ""]
    for title, key in (("By bet type", "by_type"), ("By track", "by_track"), ("By confidence", "by_confidence")):
        L.append(f"### {title}")
        L.append("")
        L.append("| Group | Bets | Hits | Misses | Unknown | Cost | Return | ROI |")
        L.append("|---|---|---|---|---|---|---|---|")
        for k, d in ru[key].items():
            L.append(f"| {k} | {d['bets']} | {d['hits']} | {d['misses']} | {d['unknown']} | ${d['cost']:.2f} | ${d['ret']:.2f} | " +
                     (f"{d['roi']:+.0%}" if d["roi"] is not None else "") + " |")
        L.append("")
    a = ru["all"]
    L.append(f"All tracks: {a['bets']} bets, {a['hits']} hits, {a['misses']} misses, ${a['cost']:.2f} cost, ${a['ret']:.2f} returned" +
             (f", ROI {a['roi']:+.0%}" if a["roi"] is not None else ""))
    return "\n".join(L)
