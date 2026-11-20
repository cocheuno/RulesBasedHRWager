"""Read a TimeformUS PP PDF through its text layer.

The PDF is a graphic layout; pdfplumber's text layer keeps one line per visual row, with some labels garbled
("Top 49 Fig" can arrive as "To 1 p 1 1 Fig" for a three-digit figure, the career record is interleaved letter
by letter).  Only the parts that survive the text layer are read:

  per race:  race number, post time, distance, surface, race type, Power Picks (three program numbers).  The Pace
             Projector is a graphic: its digits come through the text layer but not its order, so no order is claimed;
  per horse: program number (letters kept: 1A), name, sex, age, ML, weight, Top Fig (pace-adjusted speed figure),
             running style with early and late pace figures, and for every running line the date, days since
             the previous start, track, Timeform race rating, surface, distance, class, condition, odds, the
             figure string and the final pace-adjusted speed figure, plus the comment.  Works stay as text.

Nothing here is a Brisnet value.  A missing Timeform value stays None.
"""
from __future__ import annotations

import os
import re
from datetime import date

READER_VERSION = "tfus-1"

HORSE_RE = re.compile(r"^(?P<pgm>\d{1,2}[A-Z]?) (?P<name>.+?) (?P<sex>Colt|Filly|Gelding|Horse|Mare|Ridgling|Rig) \| Age (?P<age>\d+)")
TOPFIG_RE = re.compile(r"To\s*(\d)?\s*p\s*((?:\d\s?){1,3})\s*Fig")
STYLE_RE = re.compile(r"Running Style: (?P<early>\d+)(?: (?P<style>[A-Z][a-z]+))? (?P<late>\d+)")
ML_RE = re.compile(r"ML: (?P<ml>\d+-\d+)")
WT_RE = re.compile(r"WT: (?P<wt>\d{3})lbs")
SURFACES = r"Inner Turf|Outer Turf|Turf|Dirt|Synth|Tapeta|All Weather|AWT"
PAST1_RE = re.compile(r"^(?P<days>\d+) ?Days ?(?P<trk>[A-Z]{2,3}) (?:(?P<rr>\d{2,3}) )?(?:(?P<bias>[A-Za-z]+) )?\S+ (?:[A-Z]{2} )?"
                      r"(?P<surf>" + SURFACES + r") (?P<dist>\d[\d /]*? ?[FMY]) ")
FINAL_FIG_RE = re.compile(r"\s(?P<fig>\d{2,3})(?P<flag>[a-z])?\s+1\s+[A-Z]")
PAST2_RE = re.compile(r"^(?P<date>[A-Z][a-z]{2} \d{2}) (?P<cls>.*?) ?(?P<cond>Wet Fast|Fast|Firm|Good|Sloppy|Muddy|Yielding|Soft|Heavy|Slow|Frozen|Standard)"
                      r"(?P<mid>.*?)(?P<post>\bF ?\d{1,2})\s+(?P<figs>(?:(?:-|\d{1,3})\s+){3,6})(?P<comment>.*)$")
MID_WT_RE = re.compile(r"^\s*(?:(?P<field>\d{1,2})\s*)?(?P<wt>\d{3})\s*\|(?P<equip>[^|]*)\|")
MID_FIELD_RE = re.compile(r"^\s*(?P<field>\d{1,2})\b(?!\d)")
ODDS_RE = re.compile(r"(?P<odds>\d+(?:\.\d+)?-\d+)")
POST_RE = re.compile(r"(?P<date>\d{1,2}/\d{1,2}/\d{4}) (?P<time>\d{1,2}:\d{2} [AP]M)(?: (?P<rating>\d+))? ?(?P<type>.*?) (?P<surf>" + SURFACES + r")\b(?P<rest>.*)$")
DIST_RE = re.compile(r"\s(?P<dist>\d+(?: \d/\d{1,2})? ?[FMY])\s")
HEAD_RE = re.compile(r"^(?P<track>[A-Z][A-Z .'&-]+?) (?P<date>\d{1,2}/\d{1,2}/\d{4})$")
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _iso(mdy: str) -> str | None:
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", mdy or "")
    return f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else None


def _new_race() -> dict:
    return {"race_no": None, "post_time": None, "post_date": None, "distance_text": None, "surface": None, "race_type": None,
            "rating": None, "power_picks": [], "pace_projector": [], "pace_projector_basis": None, "header_lines": [], "horses": []}


def _new_horse(m: re.Match) -> dict:
    return {"pgm": m.group("pgm"), "name": m.group("name").strip(), "sex": m.group("sex"), "age": int(m.group("age")),
            "ml": None, "weight": None, "top_fig": None, "style": None, "early": None, "late": None,
            "lines": [], "works_text": None, "notes": [], "debut": None}


def parse_lines(lines, source: str | None = None) -> dict:
    """Parse the text-layer lines of a TimeformUS PP.  Races start at a line beginning with "RACE"; if the header
    is missing (a trimmed file), a program number restarting at 1 starts a race too."""
    out = {"source": "timeformus", "reader_version": READER_VERSION, "file": os.path.basename(source) if source else None,
           "track": None, "date": None, "races": [], "notes": []}
    race, horse, in_header, last_n, headers = None, None, False, 0, 0
    for raw in lines:
        line = raw.rstrip()
        if not line:
            continue
        if out["track"] is None and race is None:
            hm = HEAD_RE.match(line)
            if hm:
                out["track"], out["date"] = hm.group("track").strip(), _iso(hm.group("date"))
                continue
        if line.startswith("RACE"):
            race = _new_race(); out["races"].append(race); horse = None; in_header = True; last_n = 0; headers += 1
            continue
        hm = HORSE_RE.match(line)
        if hm:
            n = int(re.sub(r"[A-Z]", "", hm.group("pgm")))
            if race is None or (not headers and n == 1 and last_n >= 1 and hm.group("pgm") == "1"):
                if race is not None:
                    out["notes"].append(f"race split on program number restart after R{race['race_no']}")
                race = _new_race(); out["races"].append(race)
            in_header = False
            horse = _new_horse(hm)
            tf = TOPFIG_RE.search(line)
            if tf:
                horse["top_fig"] = int((tf.group(1) or "") + tf.group(2).replace(" ", ""))
            race["horses"].append(horse); last_n = n
            continue
        if in_header and race is not None:
            race["header_lines"].append(line)
            if race["race_no"] is None and re.match(r"^\d{1,2}\b", line):
                race["race_no"] = int(line.split()[0])
                dm = DIST_RE.search(line)
                if dm:
                    race["distance_text"] = dm.group("dist")
            pm = POST_RE.search(line)
            if pm and race["post_time"] is None:
                race["post_time"], race["post_date"] = pm.group("time"), _iso(pm.group("date"))
                race["rating"] = int(pm.group("rating")) if pm.group("rating") else None
                race["race_type"], race["surface"] = pm.group("type").strip() or None, pm.group("surf")
            continue
        if horse is None:
            continue
        ml = ML_RE.search(line)
        if ml:
            horse["ml"] = ml.group("ml")
            wt = WT_RE.search(line)
            horse["weight"] = int(wt.group("wt")) if wt else None
            continue
        st = STYLE_RE.search(line)
        if st:
            horse["early"], horse["late"], horse["style"] = int(st.group("early")), int(st.group("late")), st.group("style")
            continue
        if line.startswith("WORKS:"):
            horse["works_text"] = line[len("WORKS:"):].strip()
            continue
        if line.startswith("- "):
            horse["notes"].append(line[2:].strip())
            continue
        p1 = PAST1_RE.match(line)
        if p1:
            ff = None
            for ff in FINAL_FIG_RE.finditer(line):
                pass
            horse["lines"].append({"days_since_prev": int(p1.group("days")), "track": p1.group("trk"),
                                   "race_rating": int(p1.group("rr")) if p1.group("rr") else None, "bias_note": p1.group("bias"),
                                   "surface": p1.group("surf"), "distance_text": p1.group("dist").strip(),
                                   "speed_fig": int(ff.group("fig")) if ff else None, "fig_flag": ff.group("flag") if ff else None,
                                   "date": None, "date_text": None, "class": None, "condition": None, "odds": None,
                                   "figs": [], "comment": None, "raw": line})
            continue
        p2 = PAST2_RE.match(line)
        if p2 and horse["lines"] and horse["lines"][-1]["date_text"] is None:
            ln = horse["lines"][-1]
            ln["date_text"], ln["class"], ln["condition"] = p2.group("date"), p2.group("cls").strip(), p2.group("cond")
            mid = p2.group("mid")
            mw, mf, mo = MID_WT_RE.match(mid), MID_FIELD_RE.match(mid), ODDS_RE.search(mid)
            ln["field_size"] = int(mw.group("field")) if mw and mw.group("field") else (int(mf.group("field")) if mf else None)
            ln["weight"] = int(mw.group("wt")) if mw else None
            ln["equipment"] = mw.group("equip").strip() if mw else None
            ln["odds"], ln["post"] = (mo.group("odds") if mo else None), p2.group("post").replace(" ", "")
            ln["figs"] = [None if x == "-" else int(x) for x in p2.group("figs").split()]
            ln["comment"] = p2.group("comment").strip() or None
            continue
    _finish(out)
    return out


def _finish(out: dict) -> None:
    card_date = date.fromisoformat(out["date"]) if out["date"] else None
    for i, race in enumerate(out["races"], 1):
        if race["race_no"] is None:
            race["race_no"] = i
        race["horses"].sort(key=lambda h: (int(re.sub(r"[A-Z]", "", h["pgm"]) or 0), h["pgm"]))
        pgms = {h["pgm"] for h in race["horses"]}
        for h in race["horses"]:
            h["debut"] = not h["lines"]
            h["last_fig"] = h["lines"][0]["speed_fig"] if h["lines"] else None
            _date_lines(h["lines"], card_date)
            if h["top_fig"] is None and h["lines"]:
                h["notes"].append("Top Fig not readable in the text layer")
        # Power Picks: "<pgm> <name>" of this race's horses, in the order printed in the header
        header = " ".join(race["header_lines"])
        picks = []
        for h in race["horses"]:
            first = h["name"].split()[0]
            m = re.search(r"(?<![\d/])" + re.escape(h["pgm"]) + r" " + re.escape(first) + r"\b", header)
            if m:
                picks.append((m.start(), h["pgm"]))
        race["power_picks"] = [p for _, p in sorted(picks)]
        # Pace Projector: a 2-D graphic.  The text layer prints its program numbers line by line, left to right, which is
        # not the projected running order (checked against the charts' first-call leaders: 0 of 15).  The digits are kept
        # as `pace_projector_digits` for reference; the order is not claimed.
        order = []
        for ln in race["header_lines"][1:]:          # the race-number line carries distance and conditions, not the graphic
            t = re.sub(r"\([^)]*\)", " ", ln)
            t = POST_RE.sub(lambda m: m.group("rest"), t) if POST_RE.search(t) else t
            for h in race["horses"]:
                t = re.sub(r"(?<![\d/])" + re.escape(h["pgm"]) + r" " + re.escape(h["name"].split()[0]) + r"\b", " ", t)
            t = re.sub(r"\$[\d,.]+[KM]?", " ", t)
            t = re.sub(r"\d+ ?& ?\d+", " ", t)
            for tok in re.findall(r"(?<![\w/.-])(\d{1,2}[A-Z]?)(?![\w/.-])", t):
                if tok in pgms and tok not in order:
                    order.append(tok)
        race["pace_projector_digits"] = order
        race["pace_projector"] = []
        race["pace_projector_basis"] = "not readable: graphic (text-layer digits are not the running order)"
        race.pop("header_lines", None)


def _date_lines(lines: list[dict], card_date: date | None) -> None:
    """'Oct 22' has no year: lines run newest first, so the year steps back whenever the month jumps forward."""
    if not card_date:
        return
    year, prev_month = card_date.year, card_date.month
    for ln in lines:
        if not ln.get("date_text"):
            continue
        mon, day = ln["date_text"].split()
        mnum = MONTHS.get(mon)
        if not mnum:
            continue
        if mnum > prev_month:
            year -= 1
        try:
            ln["date"] = date(year, mnum, int(day)).isoformat()
        except ValueError:
            ln["date"] = None
        prev_month = mnum


def parse_source(path: str) -> dict:
    """A TimeformUS PP PDF, or its text layer saved as .txt (fixtures)."""
    if str(path).lower().endswith(".txt"):
        with open(path, encoding="utf-8", errors="replace") as fh:
            return parse_lines(fh.read().splitlines(), source=path)
    return parse_pdf(path)


def parse_pdf(path: str) -> dict:
    import pdfplumber
    lines = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            lines.extend((page.extract_text() or "").splitlines())
    return parse_lines(lines, source=path)


def identity(doc: dict) -> dict:
    return {"track": doc.get("track"), "date": doc.get("date")}


def rank_by_top_fig(horses: list[dict]) -> dict[str, int | None]:
    """1 = highest Top Fig; ties share the better rank; horses without a figure get None."""
    figs = sorted({h["top_fig"] for h in horses if h.get("top_fig") is not None}, reverse=True)
    pos = {}
    rank = 1
    for f in figs:
        pos[f] = rank
        rank += sum(1 for h in horses if h.get("top_fig") == f)
    return {h["pgm"]: pos.get(h["top_fig"]) if h.get("top_fig") is not None else None for h in horses}


def merge_timeform(card: dict, doc: dict) -> list[str]:
    """Attach the Timeform reading to a parsed Brisnet card under its own namespace: race["timeform"] (post time,
    power picks, pace projector, per-horse rank) and horse["timeform"] (figures, style, ML).  Matching is by race
    number then program number; a name check guards against the wrong file; a race the file lacks is noted."""
    notes = []
    if doc.get("date") and card.get("date") and str(doc["date"]) != str(card["date"]):
        notes.append(f"Timeform file is dated {doc['date']}, card is {card['date']}: not merged")
        return notes
    by_no = {r["race_no"]: r for r in doc.get("races", [])}
    for race in card["races"]:
        tr = by_no.get(race["race_no"])
        if not tr:
            notes.append(f"R{race['race_no']}: not in the Timeform file")
            race["timeform"] = None
            continue
        ranks = rank_by_top_fig(tr["horses"])
        tf_h = {h["pgm"]: h for h in tr["horses"]}
        race["timeform"] = {"post_time": tr.get("post_time"), "power_picks": tr.get("power_picks"),
                            "pace_projector": tr.get("pace_projector"), "pace_projector_basis": tr.get("pace_projector_basis"),
                            "rank": ranks, "surface": tr.get("surface"), "distance_text": tr.get("distance_text"),
                            "reader_version": doc.get("reader_version"), "file": doc.get("file")}
        for h in race["horses"]:
            th = tf_h.get(h["pgm"])
            if not th:
                h["timeform"] = None
                notes.append(f"R{race['race_no']} #{h['pgm']} {h['name']}: not in the Timeform file")
                continue
            if th["name"] and h.get("name") and _norm(th["name"]).split()[:1] != _norm(h["name"]).split()[:1]:
                h["timeform"] = None
                notes.append(f"R{race['race_no']} #{h['pgm']}: Timeform says {th['name']!r}, card says {h['name']!r}; not merged")
                continue
            h["timeform"] = {"top_fig": th["top_fig"], "last_fig": th.get("last_fig"), "style": th["style"], "early": th["early"],
                             "late": th["late"], "ml": th["ml"], "rank": ranks.get(h["pgm"]), "debut": th["debut"],
                             "lines": [{k: ln.get(k) for k in ("date", "track", "surface", "distance_text", "speed_fig", "figs", "condition", "odds")}
                                       for ln in th["lines"]],
                             "source": "timeformus"}
    return notes


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (name or "").lower().replace("'", "")).strip()


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(parse_pdf(sys.argv[1]), indent=1))
