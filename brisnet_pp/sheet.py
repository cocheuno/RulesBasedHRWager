"""
Brisnet "Power Play" quick sheet (the <trk><mmdd>q.pdf that accompanies the Ultimate PPs).

Read coordinate-wise, like the PP parser: the sheet is two columns (x < 305 and x >= 305, the right column
offset by 304 pt) of race blocks, each with a track/date/conditions header, a "Race" label and number, the
wager menu, the "Top 3 / Speed / Class / Pace" ranking line, and one row per horse
(Pg#, ML, Horse, Jockey, Trainer, Power Play Angles).  An asterisk before the program number marks Brisnet's
top pick (three asterisks: a 3-Star Best Bet); angle continuation lines carry no program number.

What the engine uses from it:
  * per-horse Power Play angles, in particular "ExitPossibleKeyRace" (rule F16);
  * Brisnet's own top pick / Top 3 / 3-Star Best Bets, as a benchmark for backtest.py.

Output: {"track_code", "date_text", "best_bets": [(race_no, pgm)], "races": {race_no: {"header", "wagers",
         "top3", "speed", "class", "pace", "top_pick", "horses": {pgm: {"name", "ml", "angles": [...]}}}}}
"""
from __future__ import annotations

import re

import pdfplumber

from .parser import page_rows

COL_SPLIT = 305.0
# column x-ranges, left column; the right column adds OFFSET
PGM, ML, HORSE, JOCKEY, TRAINER, ANGLES = (3, 30), (30, 47), (47, 107), (107, 167), (167, 232), (232, 305)
OFFSET = 304.0
HEADER_RE = re.compile(r"^(?P<trk>[A-Z]{2,3}) - (?P<date>\d\d/\d\d) - (?P<rest>.+)$")
PGM_RE = re.compile(r"^(?P<star>\*{1,3})?(?P<pgm>\d{1,2}[A-Z]?)$")   # * = top pick, *** = 3-Star Best Bet
ML_RE = re.compile(r"^\d+/\d+$")
RANK_RE = re.compile(r"Top 3:\s*(?P<t>[\d\-\s]*)Speed:\s*(?P<s>[\d\-\s]*)Class:\s*(?P<c>[\d\-\s]*)Pace:\s*(?P<p>[\d\-\s]*)$")
BEST_RE = re.compile(r"Race\s+(\d+)\)\s*#(\d+[A-Z]?)")


def _ranks(s: str) -> list[str]:
    return [x for x in re.split(r"[\s\-]+", s.strip()) if x]


def parse_sheet(path: str) -> dict:
    out = {"source": path, "track_code": None, "date_text": None, "best_bets": [], "races": {}}
    with pdfplumber.open(path) as pdf:
        pages = [page_rows(p, i + 1) for i, p in enumerate(pdf.pages)]
    for rows in pages:
        for side, off in ((0, 0.0), (1, OFFSET)):
            lo, hi = (0.0, COL_SPLIT) if side == 0 else (COL_SPLIT, 1e9)
            block, last_horse, expect_race_no = None, None, False
            for r in rows:
                if not r.has(lo, hi):
                    continue
                full = r.text(lo, hi)
                m = HEADER_RE.match(full)
                if m:
                    block = {"header": full, "wagers": "", "top3": [], "speed": [], "class": [], "pace": [],
                             "top_pick": None, "horses": {}, "race_no": None}
                    out["track_code"] = out["track_code"] or m.group("trk")
                    out["date_text"] = out["date_text"] or m.group("date")
                    last_horse, expect_race_no = None, False
                    continue
                for mb in BEST_RE.finditer(full):
                    out["best_bets"].append((int(mb.group(1)), mb.group(2)))
                if block is None:
                    continue
                pg = r.text(PGM[0] + off, PGM[1] + off)
                if pg == "Race":
                    expect_race_no = True
                    continue
                if expect_race_no and re.fullmatch(r"\d{1,2}", pg) and not r.has(ML[0] + off, HORSE[1] + off):
                    block["race_no"] = int(pg)
                    out["races"][block["race_no"]] = block
                    expect_race_no = False
                    continue
                mr = RANK_RE.search(full)
                if mr:
                    block["top3"], block["speed"], block["class"], block["pace"] = (_ranks(mr.group(k)) for k in "tscp")
                    continue
                if "$" in full and ("Double" in full or "Pick" in full or "Exacta" in full or "Bet 3" in full):
                    block["wagers"] = (block["wagers"] + " " + full).strip()
                    continue
                if pg.startswith("Pg#"):
                    continue
                mp = PGM_RE.match(pg.replace(" ", ""))
                mlt = r.text(ML[0] + off, ML[1] + off)
                if mp and ML_RE.match(mlt):
                    pgm = mp.group("pgm")
                    ang = re.sub(r"^\d{1,2}[A-Z]?:", "", r.text(ANGLES[0] + off, ANGLES[1] + off)).strip()
                    h = {"name": r.text(HORSE[0] + off, HORSE[1] + off), "ml": mlt,
                         "jockey": r.text(JOCKEY[0] + off, JOCKEY[1] + off), "trainer": r.text(TRAINER[0] + off, TRAINER[1] + off),
                         "angles": [ang] if ang else []}
                    block["horses"][pgm] = h
                    last_horse = h
                    if mp.group("star"):
                        block["top_pick"] = pgm
                    continue
                # angle continuation line: text only in the angles column
                ang = r.text(ANGLES[0] + off, ANGLES[1] + off)
                if ang and last_horse is not None and not r.has(lo, ANGLES[0] + off - 2):
                    last_horse["angles"].append(ang.strip())
    return out


def merge_sheet(card: dict, sheet: dict) -> list[str]:
    """Attach the sheet to a parsed card: horse["sheet_angles"] and race["brisnet"] (top pick, rankings, best bet).
    Matching is by race number and program number; a name check guards against the wrong sheet."""
    notes = []
    if sheet.get("track_code") and card.get("track_code") and sheet["track_code"] != card["track_code"]:
        notes.append(f"sheet is for {sheet['track_code']}, card is {card['track_code']}: not merged")
        return notes
    best = {(r, p) for r, p in sheet.get("best_bets", [])}
    for race in card["races"]:
        blk = sheet["races"].get(race["race_no"])
        if not blk:
            notes.append(f"R{race['race_no']}: not on the sheet")
            continue
        race["brisnet"] = {"top_pick": blk["top_pick"], "top3": blk["top3"], "speed": blk["speed"], "class": blk["class"],
                           "pace": blk["pace"], "best_bet": blk["top_pick"] if (race["race_no"], blk["top_pick"]) in best else None}
        for h in race["horses"]:
            sh = blk["horses"].get(h["pgm"])
            if not sh:
                continue
            if sh["name"] and h["name"] and sh["name"].split()[0].lower() != h["name"].split()[0].lower():
                notes.append(f"R{race['race_no']} #{h['pgm']}: sheet says {sh['name']!r}, card says {h['name']!r}; angles ignored")
                continue
            h["sheet_angles"] = sh["angles"]
    return notes


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(parse_sheet(sys.argv[1]), indent=1, default=list))
