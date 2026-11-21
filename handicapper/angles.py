"""Measured angles (no points): past-race track condition and Brisnet's race-type statistics.

Like the Power Play angles, these are labels attached to a horse and scored in the back-test and the Analysis tab
(how often a horse carrying the label won, ran in the money, and what a flat $2 win bet on it returned).  No rule
reads them; points come only after the owner sees a record.

Track condition (only when today's surface is off: wet dirt, or turf softer than firm)
  Brisnet codes on each past line: ft fast, wf wet fast, gd good, sy sloppy, my muddy, sl slow, hy heavy, fr frozen
  (a trailing s = sealed, e.g. sys); turf fm firm, gd good, yl yielding, sf soft, hy heavy.  A line counts as off
  when its condition is off for its own surface.  Labels: won before on an off track of today's surface; in the money
  there without a win; out of the money in 2 or more such starts; one such start, out of the money; no such start;
  plus the sire's mud-winner rate (18% or more) and Brisnet's off-track pedigree rating (110 or more) on wet dirt.
  Today's condition: the Equibase morning condition on the run (prospective); for races scored after the fact the
  chart's condition at post time, and the report says which.

Race type (Brisnet's statistics for this race type at this track, printed on the PPs)
  The morning-line favourite, by how often favourites win in this race type (40% or more, 30 to 39%, under 30%);
  horses 10-1 or longer on the morning line, by the share of winners at 10-1 or more (15% or more, 8 to 14%, under 8%).
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict

OFF_DIRT = {"gd", "sy", "my", "sl", "hy", "wf", "fr"}
OFF_TURF = {"gd", "yl", "sf", "hy"}
TURF_ONLY = {"fm", "yl", "sf"}
TEXT_CODES = (("wet fast", "wf"), ("fast", "ft"), ("firm", "fm"), ("good", "gd"), ("muddy", "my"), ("sloppy", "sy"), ("slow", "sl"),
              ("heavy", "hy"), ("yielding", "yl"), ("soft", "sf"), ("frozen", "fr"), ("standard", "ft"))


def norm_code(code: str | None) -> str | None:
    c = (code or "").strip().lower()
    if len(c) == 3 and c.endswith("s") and c[:2] in ("sy", "my", "gd", "wf", "sl", "hy"):
        c = c[:2]                                   # sealed
    return c or None


def code_from_text(text: str | None) -> str | None:
    t = (text or "").strip().lower()
    if not t:
        return None
    if len(t) <= 3:
        return norm_code(t)
    for word, code in TEXT_CODES:
        if t.startswith(word):
            return code
    return None


def is_off(code: str | None, surface: str | None) -> bool:
    c = norm_code(code)
    if not c:
        return False
    return c in (OFF_TURF if (surface or "").lower() == "turf" else OFF_DIRT)


def line_surface(p: dict) -> str:
    return "turf" if norm_code(p.get("track_condition")) in TURF_ONLY else (p.get("surface") or "dirt").lower()


def _rating(s) -> int | None:
    m = re.match(r"\s*(\d{2,3})", str(s or ""))
    return int(m.group(1)) if m else None


def condition_angles(h: dict, race_surface: str | None, today_code: str | None) -> list[dict]:
    surf = (race_surface or "dirt").lower()
    if not is_off(today_code, surf):
        return []
    where = "turf" if surf == "turf" else ("all-weather" if surf == "aw" else "dirt")
    lines = [p for p in h.get("pp") or [] if not p.get("dnf") and p.get("finish_pos") is not None
             and line_surface(p) == surf and is_off(p.get("track_condition"), surf)]
    wins = sum(1 for p in lines if p["finish_pos"] == 1)
    itm = sum(1 for p in lines if p["finish_pos"] <= 3)
    if not lines:
        lab = f"Off {where} today: no start on an off {where}"
    elif wins:
        lab = f"Off {where} today: won on an off {where} before"
    elif itm:
        lab = f"Off {where} today: in the money on an off {where}, no win"
    elif len(lines) >= 2:
        lab = f"Off {where} today: out of the money in 2 or more off-{where} starts"
    else:
        lab = f"Off {where} today: one off-{where} start, out of the money"
    out = [{"kind": "track condition", "label": lab}]
    if surf != "turf":
        mud = ((h.get("pedigree_stats") or {}).get("sire") or {}).get("mud_pct")
        if mud is not None and mud >= 18:
            out.append({"kind": "track condition", "label": "Off dirt today: sire's mud-winner rate 18% or more"})
        pr = _rating((h.get("pedigree_ratings") or {}).get("off"))
        if pr is not None and pr >= 110:
            out.append({"kind": "track condition", "label": "Off dirt today: Brisnet off-track pedigree rating 110 or more"})
    return out


def racetype_angles(race: dict, live: list[dict]) -> dict[str, list[dict]]:
    """live: the running horses as {pgm, ml_decimal}.  Returns {pgm: [angle, ...]}."""
    st = race.get("racetype_stats") or {}
    out: dict[str, list[dict]] = defaultdict(list)
    if not st or not live:
        return out
    priced = [x for x in live if x.get("ml_decimal") is not None]
    if priced:
        low = min(x["ml_decimal"] for x in priced)
        favs = [x for x in priced if x["ml_decimal"] == low]
        fw = st.get("fav_win_pct")
        if len(favs) == 1 and fw is not None:
            band = "40% or more" if fw >= 40 else ("30 to 39%" if fw >= 30 else "under 30%")
            out[favs[0]["pgm"]].append({"kind": "race type", "label": f"Morning-line favourite: favourites win {band} of this race type"})
    g = st.get("pct_winners_gt_10_1")
    if g is not None:
        band = "15% or more" if g >= 15 else ("8 to 14%" if g >= 8 else "under 8%")
        for x in priced:
            if x["ml_decimal"] >= 10:
                out[x["pgm"]].append({"kind": "race type", "label": f"10-1 or longer: winners at 10-1 or more are {band} of this race type"})
    return out


def race_angles(race: dict, rows: list[dict], today_code: str | None) -> dict[str, list[dict]]:
    """Angles for every running horse of one race.  race: the parsed race (horses with pp, pedigree, racetype_stats);
    rows: the engine's sheets (pgm, ml_decimal, flags)."""
    horses = {h["pgm"]: h for h in race.get("horses", [])}
    live = [{"pgm": s["pgm"], "ml_decimal": s.get("ml_decimal")} for s in rows if not s.get("flags")]
    out = racetype_angles(race, live)
    for s in rows:
        if s.get("flags") or s["pgm"] not in horses:
            continue
        out[s["pgm"]] = condition_angles(horses[s["pgm"]], race.get("surface"), today_code) + out.get(s["pgm"], [])
    return dict(out)


def today_condition(race: dict, chart: dict | None = None) -> tuple[str | None, str | None]:
    """(code, basis): the Equibase morning condition when the run had one, else the chart's condition at post time."""
    inp = race.get("inputs") or {}
    m = inp.get("track_condition_morning") or race.get("track_condition_morning")
    if code_from_text(m):
        return code_from_text(m), "morning (Equibase)"
    if chart and code_from_text(chart.get("track_condition")):
        return code_from_text(chart.get("track_condition")), "chart (post time)"
    return None, None


# ---------------------------------------------------------------------------
# Report over every card on file (prospective angles where the run carried them; else computed from the card's
# pre-race past performances, which is causal)
# ---------------------------------------------------------------------------
def angle_report(root: str, cfg: dict) -> dict:
    from handicapper.results import load_results
    from handicapper.snapshot import pre_race_by_race
    out_dir, res_dir = os.path.join(root, "data", "out"), os.path.join(root, "results")
    stats: dict = {}
    races = {"total": 0, "with_card": 0, "off_condition": 0, "basis": defaultdict(int)}
    if not os.path.isdir(res_dir):
        return {"rows": [], "races": races}
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
        snap = pre_race_by_race(out_dir, card, res, ((cfg.get("tracks") or {}).get(code or "") or {}).get("timezone"), 2)
        if not snap:
            continue
        try:
            from handicapper.results import check_identity
            check_identity(snap, res)
        except ValueError:                      # another card's results: never scored
            continue
        raw = None
        cj = os.path.join(out_dir, f"{card}.card.json")
        if os.path.exists(cj):
            with open(cj, encoding="utf-8") as fh:
                raw = {r["race_no"]: r for r in json.load(fh).get("races", [])}
        for r in snap["races"]:
            x = by_no.get(r["race_no"])
            if not x or not x.get("finish"):
                continue
            races["total"] += 1
            rows = r["sheets"]
            if any("angles" in s for s in rows):
                am = {s["pgm"]: s.get("angles") or [] for s in rows}
                tc, basis = today_condition(r, x)
            elif raw and r["race_no"] in raw:
                races["with_card"] += 1
                rr = dict(raw[r["race_no"]], inputs=r.get("inputs"), track_condition_morning=r.get("track_condition_morning"))
                tc, basis = today_condition(rr, x)
                am = race_angles(rr, rows, tc)
            else:
                continue
            if is_off(tc, r.get("surface")):
                races["off_condition"] += 1
                races["basis"][basis] += 1
            w, top3 = x["finish"][0], x["finish"][:3]
            for pgm, lst in am.items():
                for a in lst:
                    k = (a["kind"], a["label"])
                    d = stats.setdefault(k, {"kind": a["kind"], "label": a["label"], "fired": 0, "won": 0, "itm": 0, "bet": 0.0, "ret": 0.0})
                    d["fired"] += 1; d["won"] += int(pgm == w); d["itm"] += int(pgm in top3)
                    d["bet"] += 2.0; d["ret"] += (x.get("win") or 0.0) if pgm == w else 0.0
    rows = sorted(stats.values(), key=lambda d: (d["kind"], -d["fired"]))
    for d in rows:
        d["win_pct"] = round(100.0 * d["won"] / d["fired"], 1)
        d["itm_pct"] = round(100.0 * d["itm"] / d["fired"], 1)
        d["roi"] = round((d["ret"] - d["bet"]) / d["bet"], 3) if d["bet"] else None
    races["basis"] = dict(races["basis"])
    return {"rows": rows, "races": races,
            "note": "measured angles, no points; prospective where the run carried them, else computed from the card's pre-race past performances"}


def format_angle_report(rep: dict) -> str:
    r = rep["races"]
    L = [f"# Angles: track condition and race type (no points)", "",
         f"{r['total']} races with results; {r['off_condition']} on an off surface (condition from: "
         + ", ".join(f"{k} {v}" for k, v in r["basis"].items()) + ").", "",
         "| Kind | Angle | Horses | Won | Win % | In the money % | Flat $2 win |", "|---|---|---|---|---|---|---|"]
    for d in rep["rows"]:
        L.append(f"| {d['kind']} | {d['label']} | {d['fired']} | {d['won']} | {d['win_pct']} | {d['itm_pct']} | {d['roi']:+.1%} |" if d["roi"] is not None else
                 f"| {d['kind']} | {d['label']} | {d['fired']} | {d['won']} | {d['win_pct']} | {d['itm_pct']} | |")
    return "\n".join(L)


if __name__ == "__main__":
    import sys
    from handicapper.engine import load_config
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    print(format_angle_report(angle_report(root, load_config(os.path.join(root, "rules_config.json")))))
