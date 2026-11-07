#!/usr/bin/env python3
"""
Consistency checks on a parsed card (JSON from brisnet_pp.parser).

These are *internal* cross-checks: the same fact appears in several places
in a Brisnet PP (horse header, race-summary table, ranking boxes), so we
verify the parser read them consistently.  Exit status 1 if any hard
check fails.
"""
import json
import sys
from collections import Counter


def main(path: str) -> int:
    card = json.load(open(path, encoding="utf-8"))
    hard, soft = [], []
    n_h = n_pp = n_w = 0
    for race in card["races"]:
        rn = race["race_no"]
        horses = race["horses"]
        n_h += len(horses)
        pgms = [h["pgm"] for h in horses]
        if len(set(pgms)) != len(pgms):
            hard.append(f"R{rn}: duplicate program numbers {pgms}")
        # top-3 boxes name/pgm agree with the horse list
        by_pgm = {h["pgm"]: h for h in horses}
        for box, rows in (race.get("top3") or {}).items():
            for e in rows:
                h = by_pgm.get(str(e["pgm"]))
                if not h:
                    hard.append(f"R{rn}: top3 {box} pgm {e['pgm']} not among horses")
                elif h["name"] != e["name"]:
                    hard.append(f"R{rn}: top3 {box} pgm {e['pgm']} name {e['name']!r} != {h['name']!r}")
        # prime power box vs header prime power
        for e in (race.get("top3") or {}).get("prime_power", []):
            h = by_pgm.get(str(e["pgm"]))
            if h and h["prime_power"] != e["value"]:
                hard.append(f"R{rn}: prime power mismatch {h['name']} {h['prime_power']} vs {e['value']}")
        # speed-last-race box vs first PP line speed
        for e in (race.get("top3") or {}).get("speed_last_race", []):
            h = by_pgm.get(str(e["pgm"]))
            if h and h["pp"] and h["pp"][0].get("speed") != e["value"]:
                hard.append(f"R{rn}: speed-last-race mismatch {h['name']} {h['pp'][0].get('speed')} vs {e['value']}")
        # summary table joined for every horse
        for h in horses:
            n_pp += len(h["pp"])
            n_w += len(h["workouts"])
            if race.get("summary") and not h.get("summary"):
                soft.append(f"R{rn}: {h['name']} has no race-summary row")
            if h.get("summary") and h["summary"]["ml_odds"] != h["ml_odds"]:
                hard.append(f"R{rn}: {h['name']} ML odds {h['ml_odds']} vs summary {h['summary']['ml_odds']}")
            life = (h["records"].get("life") or {}).get("starts")
            if life is not None and len(h["pp"]) > min(10, life):
                hard.append(f"R{rn}: {h['name']} has {len(h['pp'])} PP lines but {life} lifetime starts")
            if life and len(h["pp"]) < min(10, life):
                soft.append(f"R{rn}: {h['name']} has {len(h['pp'])} PP lines, {life} lifetime starts (PDF may show fewer)")
            if h["run_style"] is None or h["speed_pts"] is None:
                hard.append(f"R{rn}: {h['name']} missing run style / speed points")
            if h["ml_odds"] is None:
                hard.append(f"R{rn}: {h['name']} missing morning line")
            # PP sanity
            prev = None
            for p in h["pp"]:
                if prev and p["date"] > prev:
                    hard.append(f"R{rn}: {h['name']} PP dates out of order {prev} -> {p['date']}")
                prev = p["date"]
                if not p["foreign"] and not p.get("dnf"):
                    for k in ("speed", "class_rating", "race_rating", "finish_pos"):
                        if p.get(k) is None and p.get("distance_furlongs", 9) >= 4.5:
                            soft.append(f"R{rn}: {h['name']} {p['date']} missing {k}: {p['raw'][:80]}")
                if p.get("odds") is not None and not (0.05 <= p["odds"] <= 400):
                    hard.append(f"R{rn}: {h['name']} odd odds {p['odds']}")
                if p.get("weight") is not None and not (100 <= p["weight"] <= 140):
                    hard.append(f"R{rn}: {h['name']} odd weight {p['weight']}")
        # race-level
        if race.get("distance_furlongs") is None:
            hard.append(f"R{rn}: no distance parsed from {race['header_text']!r}")
        if race.get("pars") is None:
            soft.append(f"R{rn}: no PARS line")
    print(f"{path}: {len(card['races'])} races, {n_h} horses, {n_pp} PP lines, {n_w} workouts")
    print(f"parser warnings: {len(card.get('warnings', []))}")
    for w in card.get("warnings", []):
        print("  WARN", w)
    print(f"hard failures: {len(hard)}")
    for x in hard:
        print("  FAIL", x)
    print(f"soft notes: {len(soft)}")
    for x in soft[:40]:
        print("  note", x)
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "card.json"))
