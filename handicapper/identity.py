"""Canonical identity across sources (Phase B).

One race is (track code, date, race number); one betting interest is a program number without its letter, so
1 and 1A are the same interest.  Sources: Brisnet PP (the card), Brisnet Power Play sheet, TimeformUS, the
Equibase changes page, the Equibase chart (results), later the tote.  ``reconcile`` maps every source's horses
onto the card's interests by program number, confirmed by name; a horse found by name under another program
number is a program change; anything else goes to the review list, never silently.
"""
from __future__ import annotations

import re


def norm_name(name: str | None) -> str:
    s = (name or "").lower().replace("'", "").replace("`", "")
    s = re.sub(r"\((?:[a-z]{2,3})\)", "", s)          # country suffix (IRE), (GB)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def interest_of(pgm: str | None) -> str | None:
    return re.sub(r"[A-Za-z]", "", str(pgm)) if pgm else None


def canonical_track(name_or_code: str | None, cfg: dict | None) -> str | None:
    """A track code from a code or a name in any case ("BELMONT PARK", "Belmont Park", "BEL")."""
    if not name_or_code:
        return None
    s = name_or_code.strip()
    cfg = cfg or {}
    codes = {c.upper() for c in (cfg.get("tracks") or {})} | {c.upper() for c in (cfg.get("track_aliases") or {}).values()}
    if s.upper() in codes:
        return s.upper()
    for alias, code in (cfg.get("track_aliases") or {}).items():
        if alias.lower() == s.lower():
            return code.upper()
    return None


def _match(card_horses: list[dict], pgm: str | None, name: str | None) -> tuple[dict | None, str | None]:
    """Returns (card horse, note).  note is None for a clean match, 'program change' when found by name under
    another program number, else a reason for review."""
    by_pgm = {h["pgm"]: h for h in card_horses}
    nn = norm_name(name)
    h = by_pgm.get(pgm) if pgm else None
    if h is not None:
        if not nn or not h.get("name") or norm_name(h["name"]) == nn or norm_name(h["name"]).split()[:1] == nn.split()[:1]:
            return h, None
    if nn:
        same = [x for x in card_horses if norm_name(x.get("name")) == nn]
        if len(same) == 1:
            return same[0], (f"program change: #{pgm} is the card's #{same[0]['pgm']}" if pgm and pgm != same[0]["pgm"] else None)
        if len(same) > 1:
            return None, f"name {name!r} matches {len(same)} horses in the race"
    if h is not None:
        return None, f"#{pgm}: source says {name!r}, card says {h.get('name')!r}"
    return None, f"#{pgm} {name!r} is not on the card"


def reconcile(card: dict, *, timeform: dict | None = None, changes: dict | None = None, results: dict | None = None,
              cfg: dict | None = None) -> dict:
    """Map every source onto the card.  Output per race: interests {interest: {"pgms": [...], "names": [...],
    "sources": {...}}}, program changes, scratches by interest, surface per source, review items."""
    out = {"track": {"brisnet": card.get("track"), "brisnet_code": (card.get("track_code") or "").upper() or None},
           "date": {"brisnet": card.get("date")}, "races": [], "review": [], "missing": {}}
    cfg = cfg or {}
    code = out["track"]["brisnet_code"] or canonical_track(card.get("track"), cfg)
    out["track"]["canonical"] = code
    tf_races = {r["race_no"]: r for r in (timeform or {}).get("races", [])}
    ch_races = {int(k): v for k, v in ((changes or {}).get("races") or {}).items()}
    rs_races = {r["race_no"]: r for r in (results or {}).get("races", [])}
    if timeform:
        out["track"]["timeform"] = timeform.get("track")
        out["date"]["timeform"] = timeform.get("date")
        tcode = canonical_track(timeform.get("track"), cfg)
        if code and tcode and tcode != code:
            out["review"].append(f"Timeform file is for {timeform.get('track')} ({tcode}), card is {code}")
        if timeform.get("date") and card.get("date") and str(timeform["date"]) != str(card["date"]):
            out["review"].append(f"Timeform file is dated {timeform['date']}, card is {card['date']}")
        out["missing"]["timeform"] = sorted(r["race_no"] for r in card["races"] if r["race_no"] not in tf_races)
    if changes:
        out["track"]["equibase_changes"] = changes.get("track")
        ccode = canonical_track(changes.get("track"), cfg)
        if code and ccode and ccode != code:
            out["review"].append(f"changes page is for {changes.get('track')} ({ccode}), card is {code}")
    if results:
        out["track"]["equibase_chart"] = results.get("track")
        out["date"]["equibase_chart"] = results.get("date")
        if results.get("date") and card.get("date") and str(results["date"]) != str(card["date"]):
            out["review"].append(f"results are dated {results['date']}, card is {card['date']}")
        out["missing"]["results"] = sorted(r["race_no"] for r in card["races"] if r["race_no"] not in rs_races or not rs_races[r["race_no"]].get("finish"))
    for race in card["races"]:
        rn = race["race_no"]
        interests: dict[str, dict] = {}
        names = {}
        for h in race["horses"]:
            key = interest_of(h["pgm"])
            it = interests.setdefault(key, {"pgms": [], "names": [], "coupled": False, "entry_status": [], "sources": {"brisnet": []}})
            it["pgms"].append(h["pgm"]); it["names"].append(h.get("name")); it["entry_status"].append(h.get("entry_status"))
            it["sources"]["brisnet"].append(h["pgm"])
            names.setdefault(norm_name(h.get("name")), []).append(h["pgm"])
        for it in interests.values():
            it["coupled"] = len(it["pgms"]) > 1
        review = [f"R{rn}: duplicate horse name {n!r} on #{', #'.join(p)}" for n, p in names.items() if n and len(p) > 1]
        program_changes = []
        surface = {"brisnet": race.get("surface")}
        if race.get("surface_switch"):
            surface["equibase_changes"] = race["surface_switch"].get("to")
        # Timeform
        tr = tf_races.get(rn)
        if tr:
            surface["timeform"] = (tr.get("surface") or "").lower() or None
            for th in tr["horses"]:
                h, note = _match(race["horses"], th["pgm"], th["name"])
                if h is None:
                    review.append(f"R{rn} Timeform {note}")
                    continue
                interests[interest_of(h["pgm"])]["sources"].setdefault("timeform", []).append(th["pgm"])
                if note:
                    program_changes.append({"source": "timeform", "pgm": th["pgm"], "card_pgm": h["pgm"], "name": th["name"]})
        # Equibase changes page (scratches, program/jockey changes)
        cr = ch_races.get(rn)
        scratched = []
        if cr:
            for ch in cr.get("horses", []):
                h, note = _match(race["horses"], ch.get("pgm"), ch.get("name"))
                if h is None:
                    review.append(f"R{rn} changes page {note}")
                    continue
                key = interest_of(h["pgm"])
                interests[key]["sources"].setdefault("equibase_changes", []).append(ch.get("pgm"))
                if note:
                    program_changes.append({"source": "equibase_changes", "pgm": ch.get("pgm"), "card_pgm": h["pgm"], "name": ch.get("name")})
                if any(re.match(r"scratch", c.get("text", ""), re.I) for c in ch.get("changes", [])):
                    scratched.append(h["pgm"])
        # Equibase chart (results)
        rr = rs_races.get(rn)
        if rr:
            if rr.get("surface"):
                surface["equibase_chart"] = rr["surface"].lower()
            rnames = {x["pgm"]: x.get("name") for x in rr.get("runners", []) or []}
            for pgm in rr.get("finish", []) or []:
                h, note = _match(race["horses"], pgm, rnames.get(pgm))
                if h is None:
                    review.append(f"R{rn} chart {note}")
                    continue
                interests[interest_of(h["pgm"])]["sources"].setdefault("equibase_chart", []).append(pgm)
            for pgm in rr.get("scratched", []) or []:
                if pgm not in scratched and pgm in {h["pgm"] for h in race["horses"]}:
                    scratched.append(pgm)
        # interest-level scratch: an interest is out only when every one of its program numbers is out
        for key, it in interests.items():
            it["scratched_pgms"] = [p for p in it["pgms"] if p in scratched]
            it["scratched"] = bool(it["pgms"]) and all(p in scratched for p in it["pgms"])
        known = {s for s in surface.values() if s}
        if len(known) > 1 and not race.get("surface_switch"):
            review.append(f"R{rn}: surface differs by source {surface} and no surface switch is recorded")
        out["races"].append({"race_no": rn, "interests": interests, "program_changes": program_changes, "surface": surface,
                             "scratched": scratched, "review": review})
        out["review"].extend(review)
    return out


def format_reconciliation(rec: dict) -> str:
    L = [f"# Identity: {rec['track']} {rec['date']}"]
    if rec.get("missing"):
        L.append(f"missing: {rec['missing']}")
    for r in rec["races"]:
        coupled = [f"{k} = #{'/#'.join(v['pgms'])}" for k, v in r["interests"].items() if v["coupled"]]
        L.append(f"R{r['race_no']}: {len(r['interests'])} interests" + (f"; coupled {', '.join(coupled)}" if coupled else "") +
                 (f"; program changes {r['program_changes']}" if r["program_changes"] else "") + (f"; scratched {r['scratched']}" if r["scratched"] else ""))
    if rec["review"]:
        L.append("REVIEW:")
        L.extend("- " + x for x in rec["review"])
    return "\n".join(L)
