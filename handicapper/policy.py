"""Wager policy from the owner's decisions table (docs/CAROVEX_V2_PROMPT.md, confirmed 2026-11-16, after the
frozen week 11/08 to 11/15).  Applied to the suggested wagers after they are built; every suppression is recorded
on the race (`policy.suppressed`) with its reason, and the text line is replaced by a POLICY line.

  drop_trifecta_box          four-horse trifecta box in medium and contentious races: 12 of 64, -70%  -> dropped
  medium_exacta_box_only     medium-confidence races: exacta box only (trifectas -72%)
  no_exotics_lone_speed      lone-speed call: exotics in those races -51%; the P1 weight stays
  turf_win_only              turf: win bets only (exotics -81 to -90%, win bets +11%); place / show candidates stay
  firm_turf_no_doubles       no doubles with a leg on firm turf (morning condition from the Equibase page)
  suppress_pools_not_offered the Equibase page lists pools the track will not sell: no suggestion for them
Pick 3 / Pick 4 keep being built and tracked; doubles keep (the turf rule removes the losing half).
"""
from __future__ import annotations

DEFAULT_POLICY = {"drop_trifecta_box": True, "medium_exacta_box_only": True, "no_exotics_lone_speed": True,
                  "turf_win_only": True, "firm_turf_no_doubles": True, "suppress_pools_not_offered": True}
EXOTICS = ("EXACTA", "TRIFECTA", "SUPERFECTA")
POOL_NAMES = (("superfecta", "SUPERFECTA"), ("super high five", "SUPERHIGHFIVE"), ("trifecta", "TRIFECTA"), ("exacta", "EXACTA"),
              ("quinella", "QUINELLA"), ("daily double", "DOUBLE"), ("double", "DOUBLE"), ("pick 3", "PICK3"), ("pick 4", "PICK4"),
              ("pick 5", "PICK5"), ("pick 6", "PICK6"), ("place", "PLACE"), ("show", "SHOW"))


def pools_not_offered(r: dict) -> set[str]:
    names = ((r.get("inputs") or {}).get("pools_not_offered") or [])
    out = set()
    for n in names:
        low = str(n).lower()
        for word, code in POOL_NAMES:
            if word in low:
                out.add(code)
                break
    return out


def is_firm_turf(r: dict | None) -> bool:
    if not r or r.get("surface") != "turf":
        return False
    cond = (r.get("inputs") or {}).get("track_condition_morning") or r.get("track_condition_morning") or ""
    return str(cond).strip().lower().startswith("firm")


def reason(w: dict, r: dict, by_no: dict, pol: dict) -> str | None:
    """Why this wager is suppressed in this race, or None."""
    t = w["type"]
    if pol.get("suppress_pools_not_offered") and t in pools_not_offered(r):
        return f"the track does not offer the {t.lower()} pool today (Equibase changes page)"
    if t in EXOTICS:
        if pol.get("turf_win_only") and r.get("surface") == "turf":
            return "turf: win bets only (frozen-week review: exotics -81 to -90%)"
        if pol.get("no_exotics_lone_speed") and r.get("lone_speed"):
            return f"lone-speed race (#{r['lone_speed']}): no exotics (frozen-week review: -51%)"
        if t in ("TRIFECTA", "SUPERFECTA") and r.get("confidence") != "high":
            if pol.get("medium_exacta_box_only") and r.get("confidence") == "medium":
                return "medium-confidence race: exacta box only (trifectas -72%)"
            if pol.get("drop_trifecta_box") and (w.get("box") or r.get("confidence") == "low"):
                return "contentious race: the four-horse trifecta box is dropped (12 of 64, -70%)"
    if t == "DOUBLE" and pol.get("firm_turf_no_doubles"):
        legs = [by_no.get(n) for n in (w.get("races") or [])]
        firm = [x["race_no"] for x in legs if is_firm_turf(x)]
        if firm:
            return f"no doubles through firm turf (R{', R'.join(str(n) for n in firm)})"
    return None


def apply_policy(result: dict, cfg: dict | None) -> None:
    pol = dict(DEFAULT_POLICY, **((cfg or {}).get("wager_policy") or {}))
    by_no = {r["race_no"]: r for r in result.get("races", [])}
    for r in result.get("races", []):
        keep, gone = [], []
        for w in r.get("wagers", []):
            why = reason(w, r, by_no, pol)
            if why:
                gone.append({"type": w["type"], "label": w.get("label"), "source": w.get("source"), "reason": why})
            else:
                keep.append(w)
        r["wagers"] = keep
        notes = []
        if gone:
            labels = {g["label"] for g in gone}
            r["other_wagers"] = [t for t in r.get("other_wagers", []) if t not in labels]
            for why in dict.fromkeys(g["reason"] for g in gone):
                kinds = sorted({g["type"] for g in gone if g["reason"] == why})
                line = f"POLICY: no {', '.join(k.lower() for k in kinds)} - {why}"
                notes.append(line); r["other_wagers"].append(line)
            prim = [g for g in gone if g["source"] == "primary"]
            if prim:
                r["bet_structure"] = (r.get("bet_structure") or "") + " | POLICY: " + "; ".join(dict.fromkeys(g["reason"] for g in prim))
        r["policy"] = {"suppressed": gone, "notes": notes, "settings": pol}
