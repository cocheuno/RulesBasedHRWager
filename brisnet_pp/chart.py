"""
Equibase / Brisnet result chart PDF (one race per page, e.g. 20261106BELUSA1.pdf) -> results-file race entry.

The chart is real text in the same PP2A/PP2B symbol font as the PPs, so it is read coordinate-wise like the PP
table: the runner table's columns are located from its header words (#, Horse, M/Eqt, A/S, Wt, PP, St, the
call fractions, Str, Fin, Jockey, Odds), rows between the header and "OFF AT" are runners, the "$2 Mutuel
Prices" block gives win/place/show, "... PAID $x" lines give the exotics, and the footnote paragraph gives one
trip comment per horse.  Compared with a payout-page screenshot this adds: every finisher with program number,
final odds, running positions and margins at every call, beaten lengths, equipment, weight, the track
condition, pool sizes, scratches and claims.

Output (results-file race entry, extended):
  {"race_no", "finish": [pgm...], "win", "place": {pgm: $}, "show": {pgm: $}, "exotics": [...],
   "track_condition", "surface", "official": True, "distance_text", "class_text", "weather", "times": [...],
   "final_odds": {pgm: odds-to-1}, "runners": [{"pgm","name","finish","margin","beaten","odds","jockey","weight",
   "post","equipment","calls":[...], "comment"}], "scratched": [names], "claimed": [...], "source": "chart"}
"""
from __future__ import annotations

import re

import pdfplumber

from .parser import page_rows
from .symbols import clean_name, parse_call

ORDINALS = {"FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4, "FIFTH": 5, "SIXTH": 6, "SEVENTH": 7, "EIGHTH": 8, "NINTH": 9,
            "TENTH": 10, "ELEVENTH": 11, "TWELFTH": 12, "THIRTEENTH": 13, "FOURTEENTH": 14}
# "$1 EXACTA (7-4) PAID $30.10" in the mutuel block; "$2 Daily Double (8-7) Paid $49.00; Daily Double Pool $23,490."
# and "50 CENT Pick 3 (6-8-7) Paid $40.55" in mixed case at the foot of the chart
EXOTIC_RE = re.compile(r"(?P<base>\$\d+(?:\.\d+)?|\d+\s*CENT)\s+(?P<pool>[A-Za-z][A-Za-z0-9 \-]+?)\s+\((?P<combo>[\dA-Za-z/\-,]+)\)\s+PAID\s+\$(?P<paid>[\d,]+\.\d{2})", re.I)
COND_RE = re.compile(r"\b(?:Track|Course)\s+(?P<cond>Fast|Sloppy|Muddy|Good|Firm|Yielding|Soft|Heavy|Wet Fast|Slow|Frozen|Standard)(?:\s*\((?P<note>[^)]+)\))?", re.I)
DIST_RE = re.compile(r"^(?P<dist>(?:ABOUT\s+)?[\d\s/½¼¾]+(?:FURLONGS?|MILES?|MILE|YARDS))\.?\s*(?:\(.*?\))?\s*(?P<cls>.*)$", re.I)


def _rows(page):
    return page_rows(page, 1, ytol=2.0)


def _base(s: str) -> float:
    s = s.strip().upper()
    if s.endswith("CENT"):
        return float(s.split()[0]) / 100.0
    return float(s.lstrip("$"))


def _pool(name: str) -> str:
    s = name.upper().replace(" ", "").replace("-", "")
    if s.startswith("PICK"):
        return "PICK" + s[4:]
    return {"DAILYDOUBLE": "DOUBLE", "SUPERHIGHFIVE": "SUPERHIGHFIVE", "SUPERHI5": "SUPERHIGHFIVE", "PENTAFECTA": "SUPERHIGHFIVE"}.get(s, s)


def parse_chart_page(page, race_no_hint: int | None = None) -> dict:
    return parse_chart_rows(_rows(page), race_no_hint)


def rows_to_fixture(rows) -> list:
    """Serialisable form of the rows (chars with x0/x1/top/text) for tests."""
    return [[{"text": c["text"], "x0": round(c["x0"], 2), "x1": round(c["x1"], 2), "top": round(c["top"], 2)} for c in r.chars] for r in rows]


def rows_from_fixture(data) -> list:
    from .parser import Row
    out = []
    for chars in data:
        out.append(Row(top=chars[0]["top"], chars=[dict(c) for c in chars], page=1))
    return out


def parse_chart_rows(rows, race_no_hint: int | None = None) -> dict:
    texts = [(r, r.text()) for r in rows]
    out = {"source": "chart", "official": True, "exotics": [], "runners": [], "scratched": [], "claimed": []}
    # ---- header
    for r, t in texts[:8]:
        m = re.match(r"^(?P<ord>[A-Z]+)\s+RACE\b", t)
        if m and m.group("ord") in ORDINALS:
            out["race_no"] = ORDINALS[m.group("ord")]
        md = DIST_RE.match(r.text(95, 420))
        if md and "distance_text" not in out:
            out["distance_text"] = md.group("dist").strip().title()
            cls = re.sub(r"\s+Purse.*$", "", md.group("cls"), flags=re.I).strip(" .")
            out["class_text"] = cls.title() if cls else None
            mp = re.search(r"Purse\s+\$([\d,]+)", t)
            out["purse"] = int(mp.group(1).replace(",", "")) if mp else None
        mw = re.fullmatch(r"\((?P<w>[A-Za-z ]+)\s+(?P<deg>\d+)\)", r.text(95, 200).strip())
        if mw and "weather" not in out:
            out["weather"] = f"{mw.group('w').strip()} {mw.group('deg')}"
        if re.match(r"^[A-Z][a-z]+ \d+(?:st|nd|rd|th)?, \d{4}$", r.text(0, 95)):
            out["date_text"] = r.text(0, 95)
        if r.x_min < 20 and re.match(r"^[A-Z][A-Za-z .]+$", r.text(0, 95)) and "track" not in out and "RACE" not in t:
            out["track"] = r.text(0, 95)
    if "race_no" not in out and race_no_hint:
        out["race_no"] = race_no_hint
    # ---- runner table: columns from the header words
    hdr = next((r for r, t in texts if "Horse" in t and "Fin" in t and "Jockey" in t), None)
    if hdr is None:
        raise ValueError("no runner table header found")
    toks = hdr.tokens()
    names = [t["text"] for t in toks]
    xs = [t["x0"] for t in toks]
    col = {}
    for i, nm in enumerate(names):
        col[nm] = (xs[i] - 5, xs[i + 1] - 5 if i + 1 < len(xs) else 1e9)
    calls = [nm for nm in names if nm in ("¼", "½", "¾", "Str", "1m", "1¼", "1½", "2m", "3/16", "3/8", "5/16")]
    start_x = col["#"][0]
    runners = []
    for r, t in texts:
        if r.top <= hdr.top:
            continue
        if t.startswith("OFF AT") or t.startswith("Time ") or "Mutuel Prices" in t:
            break
        pg = r.text(start_x, col["Horse"][0]).strip()
        if not re.fullmatch(r"\d{1,2}[A-Z]?", pg):
            continue
        rec = {"pgm": pg, "name": clean_name(r.text(col["Horse"][0], col["M/Eqt."][0] if "M/Eqt." in col else col["Horse"][1])).strip(),
               "last_raced": r.text(0, start_x).strip() or None,
               "equipment": r.text(col["M/Eqt."][0], col["A/S"][0]).strip() if "M/Eqt." in col else "",
               "age_sex": r.text(col["A/S"][0], col["Wt"][0]).strip() if "A/S" in col else "",
               "weight": None, "post": None, "calls": [], "comment": None}
        wt = r.text(col["Wt"][0], col["PP"][0]) if "Wt" in col else ""
        rec["weight"] = int(wt) if wt.isdigit() else None
        pp = r.text(col["PP"][0], col["St"][0] if "St" in col else col["PP"][1]) if "PP" in col else ""
        rec["post"] = int(pp) if pp.isdigit() else None
        if "St" in col:
            rec["start"] = parse_call(r.text(col["St"][0], col["St"][1]))
        for c in calls:
            rec["calls"].append({"call": c, **parse_call(r.text(col[c][0], col[c][1]))})
        fin = parse_call(r.text(col["Fin"][0], col["Jockey"][0]))
        rec["finish"], rec["margin"] = fin.get("pos"), fin.get("lengths")
        rec["jockey"] = r.text(col["Jockey"][0], col["Odds"][0]).strip() if "Odds" in col else r.text(col["Jockey"][0], 1e9).strip()
        od = r.text(col["Odds"][0], 1e9).strip().replace("*", "") if "Odds" in col else ""
        try:
            rec["odds"] = float(od)
        except ValueError:
            rec["odds"] = None
        runners.append(rec)
    runners.sort(key=lambda x: (x["finish"] is None, x["finish"] or 99))
    beaten = 0.0
    for i, rec in enumerate(runners):
        rec["beaten"] = 0.0 if i == 0 else round(beaten, 2)
        beaten += rec["margin"] or 0.0
    out["runners"] = runners
    out["finish"] = [x["pgm"] for x in runners if x["finish"]]
    out["final_odds"] = {x["pgm"]: x["odds"] for x in runners if x["odds"] is not None}
    # ---- off / condition / times
    for r, t in texts:
        if t.startswith("OFF AT"):
            mc = COND_RE.search(t)
            if mc:
                out["track_condition"] = mc.group("cond").upper()
                if mc.group("note"):
                    out["track_condition"] += " (" + mc.group("note") + ")"
                out["surface"] = "TURF" if "Course" in t else "DIRT"
            mo = re.search(r"OFF AT\s+([\d:]+)", t)
            out["off_at"] = mo.group(1) if mo else None
            out["start_note"] = (re.search(r"Start\s+(.*?)\.\s", t + " ") or [None, None])[1]
        if t.startswith("Time "):
            mt = re.search(r"\(([^)]+)\)", t)
            out["times"] = []
            for x in (mt.group(1).replace(" ", "").split(",") if mt else []):
                mins, _, secs = x.rpartition(":")
                try:
                    out["times"].append(round((int(mins) if mins else 0) * 60 + float(secs), 2))
                except ValueError:
                    pass
    # ---- mutuels: "1-BLETCHLEY ..... 5.64 3.82 2.84"; amounts by column position relative to the first (win) row.
    # The winner's row defines the columns: three amounts = win/place/show, two = win/place (no show wagering in a
    # four-horse field), one = win only.  Equibase prints no column header, so the count is the only signal.
    win_x = place_x = show_x = None
    mutuel_rows = []
    for r, t in texts:
        tt = t.replace("$2 Mutuel Prices:", "").strip()
        m = re.match(r"^(\d{1,2}[A-Z]?)-\s*[A-Z]", tt)
        if m and re.search(r"\d+\.\d{2}\s*$", tt):
            amts = [(tk["x0"], float(tk["text"])) for tk in r.tokens() if re.fullmatch(r"\d+\.\d{2}", tk["text"]) and tk["x0"] > 150]
            if amts:
                mutuel_rows.append((m.group(1), amts))
    if mutuel_rows:
        first = mutuel_rows[0][1]
        cols = [a[0] for a in first][:3]
        win_x = cols[0]
        place_x = cols[1] if len(cols) > 1 else None
        show_x = cols[2] if len(cols) > 2 else None
        out["place"], out["show"] = {}, {}
        out["pools"] = ["win", "place", "show"][:len(cols)]
        for pg, amts in mutuel_rows:
            for x, v in amts:
                if abs(x - win_x) < 8:
                    out["win"] = v
                elif place_x is not None and abs(x - place_x) < 8:
                    out["place"][pg] = v
                elif show_x is not None and abs(x - show_x) < 8:
                    out["show"][pg] = v
                elif show_x is None:          # two-column chart: anything right of the win column is a place price
                    out["place"][pg] = v
                else:
                    out["show"][pg] = v
    # ---- exotics
    for r, t in texts:
        for m in EXOTIC_RE.finditer(t):
            out["exotics"].append({"type": _pool(m.group("pool")), "base": _base(m.group("base")),
                                   "combo": m.group("combo").replace("-", "/"), "payout": float(m.group("paid").replace(",", ""))})
    # ---- footnotes: comments per horse, scratches, claims
    foot_start = next((i for i, (r, t) in enumerate(texts) if re.match(r"^(Bay|Dk|Ch|Gr|B\.|Dark|Chestnut|Gray|Grey|Roan|Brown|Black|Blk)", t) and "by" in t), None)
    if foot_start is not None:
        para = []
        for r, t in texts[foot_start + 1:]:
            if re.match(r"^(Owners|Trainers|Breeders|Scratched|Claimed|Footnotes|\$\d|Copyright)", t):
                break
            para.append(t)
        starts = split_comments(" ".join(para), [(x["name"], x["pgm"]) for x in runners])
        for x in runners:
            x["comment"] = starts.get(x["pgm"])
    LABEL = re.compile(r"^(Scratched|Claimed|Claiming Prices|Owners|Trainers|Breeders|Footnotes|Copyright|\$|\d+ CENT)", re.I)
    for i, (r, t) in enumerate(texts):
        if t.startswith("Scratched-") or t.startswith("Claimed-") or t.startswith("Claiming Prices"):
            full = t
            for rr, tt in texts[i + 1:i + 6]:          # a wrapped list continues on rows that carry no label
                if LABEL.match(tt) or rr.x_min > 40:
                    break
                full += " " + tt
            if full.startswith("Scratched-"):
                out["scratched"] = [s.strip() for s in re.split(r";|,(?=\s*[A-Z])", full[len("Scratched-"):]) if s.strip()]
            else:
                out["claimed"].append(full)
    return out


def split_comments(prose: str, names: list[tuple[str, str]]) -> dict:
    """The footnote paragraph -> {pgm: comment}.  A horse's comment starts where its name (in capitals) opens a
    sentence; a rival's name inside another horse's sentence does not start a new comment."""
    caps = sorted(((nm.upper(), pg) for nm, pg in names), key=lambda z: -len(z[0]))
    positions = []
    for nm, pg in caps:
        for m in re.finditer(r"(?<![A-Z'])" + re.escape(nm) + r"(?![A-Z'])", prose):
            before = prose[max(0, m.start() - 2):m.start()]
            if m.start() == 0 or before.endswith(". ") or before.endswith(".") or before.endswith("; "):
                positions.append((m.start(), pg, nm))
    positions.sort()
    out = {}
    for i, (pos, pg, nm) in enumerate(positions):
        if pg in out:
            continue
        end = positions[i + 1][0] if i + 1 < len(positions) else len(prose)
        out[pg] = prose[pos:end].strip()
    return out


def parse_chart(path: str) -> list[dict]:
    """Every race page in a chart PDF (a single-race download has one page)."""
    m = re.search(r"USA(\d+)\.pdf$", path, re.I)
    hint = int(m.group(1)) if m else None
    out = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            try:
                out.append(parse_chart_page(page, hint if len(pdf.pages) == 1 else None))
            except ValueError:
                continue
    return out


def chart_to_result(chart: dict) -> dict:
    """The results-file entry (what backtest.py / wagering.py read) plus the extras, under the same keys."""
    keys = ("race_no", "finish", "win", "place", "show", "exotics", "track_condition", "surface", "official", "distance_text",
            "class_text", "purse", "weather", "times", "off_at", "final_odds", "runners", "scratched", "claimed", "source", "track")
    return {k: chart[k] for k in keys if k in chart}


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps([chart_to_result(c) for c in parse_chart(sys.argv[1])], indent=1, ensure_ascii=False))
