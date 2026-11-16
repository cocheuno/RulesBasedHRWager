"""Field provenance for the Brisnet Ultimate PP (Phase B).

Three jobs, none of which changes a score:

1. ``audit_fields(card)``: every key the parser writes for a race, a horse, a running line and a work, and whether
   the rules (features.py / engine.py) read it.  The owner pays for every field; this says which are still unread.
2. ``horse_record(h, race, as_of)``: the horse's raw parser fields with their source and date, the running lines
   and works each with its own date, and missingness flags.  With ``as_of``, no line or work dated after that
   day is included: a feature vector "as of T" is built from this filtered copy (``features_as_of``).
3. ``missing_flags(h)``: what the PP does not say about this horse (no figures, no works, no trainer stats ...),
   so a rule can tell "absent" from "zero" and the Desk can show it.
"""
from __future__ import annotations

import os
import re
from datetime import date

SOURCE = "brisnet_pp"
_HERE = os.path.dirname(os.path.abspath(__file__))


def _read_keys(paths=("features.py", "engine.py")) -> str:
    out = []
    for p in paths:
        with open(os.path.join(_HERE, p), encoding="utf-8") as fh:
            out.append(fh.read())
    return "\n".join(out)


def _is_read(key: str, src: str) -> bool:
    return re.search(r'["\']%s["\']' % re.escape(key), src) is not None


def audit_fields(card: dict) -> dict:
    """{"race": {"read": [...], "unread": [...]}, "horse": ..., "pp_line": ..., "work": ...} over the keys that occur
    in this card.  The check is lexical (the key appears quoted in the rules code), good enough for an inventory."""
    src = _read_keys()
    keys = {"race": set(), "horse": set(), "pp_line": set(), "work": set()}
    for r in card.get("races", []):
        keys["race"].update(k for k in r if k not in ("horses",))
        for h in r.get("horses", []):
            keys["horse"].update(h.keys())
            for p in h.get("pp", []) or []:
                keys["pp_line"].update(p.keys())
            for w in h.get("workouts", []) or []:
                keys["work"].update(w.keys())
    out = {}
    for group, ks in keys.items():
        read = sorted(k for k in ks if _is_read(k, src))
        out[group] = {"read": read, "unread": sorted(ks - set(read)), "count": len(ks)}
    return out


def format_audit(audit: dict) -> str:
    L = ["# Parser field audit", ""]
    for group in ("race", "horse", "pp_line", "work"):
        g = audit.get(group) or {}
        L.append(f"## {group}: {len(g.get('read', []))} read by the rules, {len(g.get('unread', []))} not read (of {g.get('count', 0)})")
        L.append("- unread: " + (", ".join(g.get("unread", [])) or "none"))
        L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Missingness
# ---------------------------------------------------------------------------
def missing_flags(h: dict) -> list[str]:
    """Names of the things this horse's PP does not provide.  Absent is not zero."""
    flags = []
    pp = [p for p in (h.get("pp") or []) if not p.get("dnf")]
    if not h.get("pp"):
        flags.append("no_running_lines")
    if pp and not any(p.get("speed") is not None for p in pp):
        flags.append("no_speed_figures")
    if pp and not any(p.get("e1") is not None and p.get("e2") is not None for p in pp):
        flags.append("no_pace_figures")
    if pp and not any(p.get("lp") is not None for p in pp):
        flags.append("no_late_pace_figures")
    if pp and not any(p.get("class_rating") is not None for p in pp):
        flags.append("no_class_ratings")
    if not h.get("workouts"):
        flags.append("no_works")
    if not h.get("ml_odds"):
        flags.append("no_morning_line")
    if h.get("run_style") is None:
        flags.append("no_run_style")
    if h.get("speed_pts") is None:
        flags.append("no_speed_points")
    if h.get("prime_power") is None:
        flags.append("no_prime_power")
    if not h.get("trainer_stats"):
        flags.append("no_trainer_stats")
    if not h.get("jockey_stats"):
        flags.append("no_jockey_stats")
    if not h.get("pedigree_ratings"):
        flags.append("no_pedigree_ratings")
    if not h.get("pedigree_stats"):
        flags.append("no_pedigree_stats")
    if not (h.get("records") or {}).get("life"):
        flags.append("no_record")
    if h.get("days_since_last") is None and pp:
        flags.append("no_days_since_last")
    return flags


# ---------------------------------------------------------------------------
# Records with source and date; as-of filtering
# ---------------------------------------------------------------------------
RAW_HORSE_KEYS = ("pgm", "post", "entry_status", "name", "ml_odds", "run_style", "speed_pts", "prime_power", "prime_power_rank",
                  "age", "sex", "weight", "lasix", "first_lasix", "blinkers_change", "trainer", "jockey", "days_since_last",
                  "lifetime_starts", "first_time_starter", "claim_price", "apprentice_allowance", "sire", "dam", "dam_sire",
                  "bred_state", "owner", "breeder", "color", "foal_month", "sale", "stud_fee", "silks", "name_flag")


def _le(d: str | None, as_of: str | None) -> bool:
    """True when the line/work date is on or before as_of (undated items are kept and flagged by the caller)."""
    if not as_of or not d:
        return True
    try:
        return date.fromisoformat(str(d)[:10]) <= date.fromisoformat(str(as_of)[:10])
    except ValueError:
        return True


def horse_as_of(h: dict, as_of: str | None) -> dict:
    """A copy of the horse whose running lines and works are dated on or before ``as_of`` (ISO date).  The card's
    own fields (ML, records, stats) carry the card date and are kept as printed."""
    if not as_of:
        return h
    c = dict(h)
    c["pp"] = [p for p in (h.get("pp") or []) if _le(p.get("date"), as_of)]
    c["workouts"] = [w for w in (h.get("workouts") or []) if _le(w.get("date"), as_of)]
    return c


def horse_record(h: dict, race: dict, as_of: str | None = None) -> dict:
    """Raw fields with provenance, lines and works with their own dates, derived summaries kept apart."""
    card_date = race.get("race_date") or race.get("date")
    hh = horse_as_of(h, as_of)
    raw = {k: {"value": h.get(k), "source": SOURCE, "as_of": card_date} for k in RAW_HORSE_KEYS if k in h}
    lines = [{"date": p.get("date"), "source": SOURCE, "track": p.get("track"), "surface": p.get("surface"), "distance_furlongs": p.get("distance_furlongs"),
              "speed": p.get("speed"), "e1": p.get("e1"), "e2": p.get("e2"), "lp": p.get("lp"), "class_rating": p.get("class_rating"),
              "finish_pos": p.get("finish_pos"), "beaten_lengths": p.get("beaten_lengths"), "odds": p.get("odds"), "comment": p.get("comment"),
              "dnf": p.get("dnf"), "undated": p.get("date") is None} for p in hh.get("pp") or []]
    works = [{"date": w.get("date"), "source": SOURCE, "track": w.get("track"), "distance_furlongs": w.get("distance_furlongs"),
              "time": w.get("time"), "rank": w.get("rank"), "of": w.get("of"), "bullet": w.get("bullet"), "undated": w.get("date") is None}
             for w in hh.get("workouts") or []]
    derived = {"records": {"value": h.get("records"), "source": SOURCE, "as_of": card_date, "note": "Brisnet career/surface boxes as printed"},
               "trainer_stats": {"value": h.get("trainer_stats"), "source": SOURCE, "as_of": card_date},
               "jockey_stats": {"value": h.get("jockey_stats"), "source": SOURCE, "as_of": card_date},
               "pedigree_ratings": {"value": h.get("pedigree_ratings"), "source": SOURCE, "as_of": card_date},
               "pedigree_stats": {"value": h.get("pedigree_stats"), "source": SOURCE, "as_of": card_date},
               "positives": {"value": h.get("positives"), "source": SOURCE + ":comments", "as_of": card_date},
               "negatives": {"value": h.get("negatives"), "source": SOURCE + ":comments", "as_of": card_date}}
    out = {"pgm": h.get("pgm"), "name": h.get("name"), "as_of": as_of or card_date, "raw": raw, "lines": lines, "works": works,
           "derived": derived, "missing": missing_flags(hh),
           "excluded_after_as_of": {"lines": len(h.get("pp") or []) - len(lines), "works": len(h.get("workouts") or []) - len(works)}}
    if h.get("sheet"):
        out["sheet"] = {"value": h["sheet"], "source": "brisnet_power_play", "as_of": card_date}
    if h.get("timeform"):
        out["timeform"] = {"value": h["timeform"], "source": "timeformus", "as_of": card_date}
    return out


def features_as_of(h: dict, race: dict, as_of: str | None):
    """The rules' feature vector computed from the as-of copy: nothing dated after as_of is in it."""
    from handicapper.features import horse_features
    return horse_features(horse_as_of(h, as_of), race)


def card_records(card: dict, as_of: str | None = None) -> dict:
    return {"track": card.get("track"), "track_code": card.get("track_code"), "date": card.get("date"), "as_of": as_of or card.get("date"),
            "races": [{"race_no": r["race_no"], "horses": [horse_record(h, r, as_of) for h in r["horses"]]} for r in card.get("races", [])]}


if __name__ == "__main__":
    import json
    import sys
    with open(sys.argv[2] if len(sys.argv) > 2 else sys.argv[1], encoding="utf-8") as fh:
        card = json.load(fh)
    if sys.argv[1] == "audit":
        print(format_audit(audit_fields(card)))
    else:
        print(json.dumps(card_records(card, sys.argv[3] if len(sys.argv) > 3 else None), indent=1, default=str))
