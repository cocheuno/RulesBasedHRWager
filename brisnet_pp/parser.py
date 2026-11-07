"""
Brisnet "Ultimate PP's w/ QuickPlay Comments" PDF parser.

Strategy
--------
The PDF is laid out on a fixed coordinate grid (612 x 792 pt) and every
column of the past-performance table sits at the same x-position on every
page.  We therefore work from *character coordinates* (pdfplumber) rather
than from extracted text: characters are grouped into rows by their `top`
coordinate and sliced into columns by `x0`.  This is deterministic and
survives the kerning quirks that make text extraction unreliable.

Output is a plain dict (JSON-serialisable):

{
  "source": "...pdf", "track": "Del Mar", "date": "2026-11-06",
  "races": [ { race header..., "horses": [ {...} ], "summary": {...}, "bias": {...} } ]
}
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

import pdfplumber

from .symbols import (
    FRAC_CLASS, MARGIN_CLASS, SUP_CLASS, SYM_AGE_3UP, SYM_AGE_4UP, SYM_AW,
    SYM_CLAIM_C, SYM_FILLIES, SYM_FIRST_LASIX, SYM_NAME_FLAG, SYM_NEG,
    SYM_POS, SYM_STATEBRED, SYM_TURF, SYM_WORK_TURF, TRACK_CONDITIONS,
    clean_name, decode_sup, parse_call, parse_distance, parse_time, sup_to_int,
)

# --------------------------------------------------------------------------
# Low level geometry helpers
# --------------------------------------------------------------------------


@dataclass
class Row:
    top: float
    chars: list = field(default_factory=list)
    page: int = 0

    def text(self, x0: float = -1e9, x1: float = 1e9, gap: float = 1.0) -> str:
        """Text of the chars whose x0 lies in [x0, x1), with spaces inserted on gaps."""
        cs = sorted((c for c in self.chars if x0 <= c["x0"] < x1), key=lambda c: c["x0"])
        out = []
        prev = None
        for c in cs:
            if prev is not None and c["x0"] - prev["x1"] > gap:
                out.append(" ")
            out.append(c["text"])
            prev = c
        return re.sub(r"[ ]{2,}", " ", "".join(out)).strip()

    def tokens(self, x0: float = -1e9, x1: float = 1e9, gap: float = 1.2) -> list[dict]:
        cs = sorted((c for c in self.chars if x0 <= c["x0"] < x1), key=lambda c: c["x0"])
        toks, cur = [], None
        for c in cs:
            if c["text"] == " ":
                if cur:
                    toks.append(cur)
                    cur = None
                continue
            if cur and c["x0"] - cur["x1"] <= gap:
                cur["text"] += c["text"]
                cur["x1"] = c["x1"]
            else:
                if cur:
                    toks.append(cur)
                cur = {"text": c["text"], "x0": c["x0"], "x1": c["x1"]}
        if cur:
            toks.append(cur)
        return toks

    def has(self, x0: float, x1: float) -> bool:
        return any(x0 <= c["x0"] < x1 and c["text"].strip() for c in self.chars)

    @property
    def x_min(self) -> float:
        return min((c["x0"] for c in self.chars if c["text"].strip()), default=1e9)


def page_rows(page, page_no: int, ytol: float = 1.6) -> list[Row]:
    rows: list[Row] = []
    for c in sorted(page.chars, key=lambda c: (c["top"], c["x0"])):
        if rows and abs(c["top"] - rows[-1].top) <= ytol:
            rows[-1].chars.append(c)
        else:
            rows.append(Row(top=c["top"], chars=[c], page=page_no))
    return rows


def merge_rows(rows: list[Row], ytol: float) -> list[Row]:
    """Merge rows whose tops are within ytol of the *first* row of the group."""
    out: list[Row] = []
    for r in rows:
        if out and abs(r.top - out[-1].top) <= ytol and r.page == out[-1].page:
            out[-1].chars.extend(r.chars)
        else:
            out.append(Row(top=r.top, chars=list(r.chars), page=r.page))
    return out


def num(s: str | None):
    if s is None:
        return None
    s = s.strip().replace(",", "").replace("$", "")
    if s in ("", "-", "NA", "N/A"):
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return None


def pct(s: str | None):
    if not s:
        return None
    return num(s.replace("%", ""))


# --------------------------------------------------------------------------
# Regexes
# --------------------------------------------------------------------------
DATE_RE = re.compile(r"^(\d{2})([A-Z][a-z]{2})(\d{2})")
WORK_RE = re.compile(
    r"(?P<bullet>" + re.escape(SYM_NEG) + r")?\s*(?P<date>\d{2}[A-Z][a-z]{2}(?:'\d{2})?)\s+(?P<trk>[A-Za-z]{2,4})\s+(?P<turf>" + re.escape(SYM_WORK_TURF) +
    r"\s*\(d\)\s*)?(?P<dist>\d+f)\s+(?P<cond>[a-z]{2,3})\s+(?P<time>(?:\d*:)?\d\d" + SUP_CLASS + r"?)\s*"
    r"(?P<type>[HBhbg]+)\s*(?P<rank>\d+)/(?P<of>\d+)"
)
# US-format lines run at foreign tracks (no Brisnet pace/speed figures)
FOREIGN_TRACK_CODES = {"Mey", "Ksa"}
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jly", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
MONTHS["Jul"] = 7

RECORD_RE = re.compile(
    r"(?P<starts>\d+)\s*(?P<w>\d+)\s*-\s*(?P<p>\d+)\s*-\s*(?P<s>\d+)\s*\$(?P<earn>[\d,]+)\s*(?P<best>\d+)?"
)


def parse_record(text: str) -> dict | None:
    m = RECORD_RE.search(text)
    if not m:
        return None
    return {
        "starts": int(m.group("starts")),
        "win": int(m.group("w")),
        "place": int(m.group("p")),
        "show": int(m.group("s")),
        "earnings": int(m.group("earn").replace(",", "")),
        "best_speed": num(m.group("best")),
    }


# --------------------------------------------------------------------------
# Column definitions (x0 boundaries) for the past performance line
# --------------------------------------------------------------------------
PP_COLS = {
    "date_trk": (0, 50),
    "dist": (50, 83),
    "times": (83, 147.5),
    "age": (147.5, 155),
    "rr": (155, 166),
    "racetype": (166, 205.5),
    "cr": (205.5, 214.5),
    "e1": (215.5, 228.5),
    "e2": (228.5, 243),
    "lp": (243, 255.5),
    "c1": (255.5, 267.5),
    "c2": (267.5, 279.5),
    "spd": (279.5, 290),
    "pp": (290, 299),
    "st": (299, 314),
    "call1": (314, 328.5),
    "call2": (328.5, 343),
    "str": (343, 359),
    "fin": (359, 374),
    "jockey": (374, 421.5),
    "med": (421.5, 431.5),
    "odds": (431.5, 450.5),
    "rest": (450.5, 700),
}


class ParseError(Exception):
    pass


# --------------------------------------------------------------------------
# The parser
# --------------------------------------------------------------------------
class BrisnetPPParser:
    def __init__(self, pdf_path: str, verbose: bool = False):
        self.pdf_path = pdf_path
        self.verbose = verbose
        self.card = {"source": pdf_path, "track": None, "date": None, "races": []}
        self.warnings: list[str] = []

    # ---------------------------------------------------------------- utils
    def warn(self, msg: str):
        self.warnings.append(msg)
        if self.verbose:
            print("WARN:", msg, file=sys.stderr)

    # ---------------------------------------------------------------- main
    def parse(self) -> dict:
        with pdfplumber.open(self.pdf_path) as pdf:
            pages = [page_rows(p, i + 1) for i, p in enumerate(pdf.pages)]

        race: dict | None = None
        for pno, rows in enumerate(pages, 1):
            if not rows:
                continue
            header = self._page_header(rows)
            if header is None:
                self.warn(f"page {pno}: no race header found; skipped")
                continue
            race_no = header["race_no"]
            body = [r for r in rows if r.top > 40 and r.top < 770]
            if self.card["track"] is None:
                self.card["track"] = header["track"]
                self.card["date"] = header["date"]

            kind = self._page_kind(rows)
            if race is None or race["race_no"] != race_no:
                race = {"race_no": race_no, "header_text": header["conditions_line"], "horses": [],
                        "pages": [], "summary": None, "bias": None, "rankings": None, "racetype_stats": None}
                self.card["races"].append(race)
            race["pages"].append(pno)

            # A page may hold horses followed by the race-summary section; split there.
            split = next((i for i, r in enumerate(body) if self._is_summary_start(r)), None)
            horse_rows = body if split is None else body[:split]
            summary_rows = [] if split is None else body[split:]
            if kind == "first":
                self._parse_race_header(horse_rows, race)
            if kind != "summary":
                self._parse_horses(horse_rows, race)
            if summary_rows:
                self._parse_summary_page(summary_rows, race)

        for race in self.card["races"]:
            race["field_size"] = len(race["horses"])
            self._derive_race_fields(race)
            for h in race["horses"]:
                self._derive_horse_fields(h, race)
        # today's track code (e.g. DMR): the code on every horse's track-record line
        codes = Counter(h["records"].get("track_code") for r in self.card["races"] for h in r["horses"] if h["records"].get("track_code"))
        self.card["track_code"] = codes.most_common(1)[0][0] if codes else None
        self.card["warnings"] = self.warnings
        return self.card

    # ------------------------------------------------------------ page level
    def _page_header(self, rows: list[Row]) -> dict | None:
        top_rows = [r for r in rows if r.top < 35]
        txt = " ".join(r.text() for r in top_rows)
        m = re.search(r"Race\s+(\d+)", txt)
        if not m:
            return None
        race_no = int(m.group(1))
        trk = None
        for r in top_rows:
            t = r.text(100, 470)
            mm = re.match(r"^(.*?)\s+Race\s+\d+", t)
            if mm and not trk:
                trk = mm.group(1).strip()
        cond_line = ""
        date = None
        for r in top_rows:
            t = r.text(200, 540)
            md = re.search(r"([A-Z][a-z]+day),\s+([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})", t)
            if md:
                cond_line = t
                try:
                    date = datetime.strptime(f"{md.group(2)} {md.group(3)} {md.group(4)}", "%B %d %Y").date().isoformat()
                except ValueError:
                    date = None
        return {"race_no": race_no, "track": trk, "date": date, "conditions_line": cond_line}

    @staticmethod
    def _is_summary_start(r: Row) -> bool:
        t = r.text()
        return ("RACETYPE STATS" in t or t.startswith("Track Bias Stats") or t == "Race Summary"
                or r.text(0, 100).startswith("# Horse Name"))

    def _page_kind(self, body: list[Row]) -> str:
        for r in body[:12]:
            t = r.text()
            if "RACETYPE STATS" in t:
                return "summary"
            if re.search(r"#\s+Speed Last Race", t):
                return "first"
        return "continuation"

    # ------------------------------------------------------------ race header
    def _parse_race_header(self, body: list[Row], race: dict):
        # Top-3 boxes: four columns
        boxes = {"speed_last_race": (0, 160), "prime_power": (160, 320), "class_rating": (320, 470), "best_speed_at_dist": (470, 612)}
        top3 = {k: [] for k in boxes}
        cond_lines = []
        wagers = []
        for r in body:
            if r.top > 180:
                break
            t = r.text()
            if 45 < r.top < 75:
                for k, (a, b) in boxes.items():
                    tt = r.text(a, b)
                    m = re.match(r"^(\d+)\s+(.+?)\s+([\d.]+)$", tt)
                    if m:
                        top3[k].append({"pgm": int(m.group(1)), "name": m.group(2), "value": num(m.group(3))})
            elif "PARS:" in t:
                m = re.search(r"PARS:\s*(\d+)\s+(\d+)/\s*(\d+)\s+(\d+)", t)
                if m:
                    race["pars"] = {"e1": int(m.group(1)), "e2": int(m.group(2)), "late": int(m.group(3)), "speed": int(m.group(4))}
                w = r.text(60, 400)
                if "/" in w and "$" in w:
                    wagers.append(w)
            elif r.x_min >= 60 and r.x_min < 80 and ("$" in t or "Pick" in t or "Parlay" in t or "Exacta" in t) and r.top < 125:
                wagers.append(t)
            elif r.x_min >= 60 and r.x_min < 80 and r.top >= 125:
                cond_lines.append(t)
        race["top3"] = top3
        race["wagers"] = " ".join(wagers)
        race["conditions"] = " ".join(cond_lines)
        m = re.search(r"Purse\s+\$([\d,]+)", race["conditions"])
        race["purse"] = int(m.group(1).replace(",", "")) if m else None
        m = re.search(r"Post Time:\s*([^\n]+)", race["conditions"])
        race["post_time"] = m.group(1).strip() if m else None

    def _derive_race_fields(self, race: dict):
        h = race.get("header_text") or ""
        # e.g. "™MC 16000 1 Mile 3&up, F & M Friday, November 06, 2026"
        race["fillies_mares"] = SYM_FILLIES in h
        race["state_bred"] = SYM_STATEBRED in h
        hc = clean_name(h)
        m = re.match(r"^(?P<cls>.+?)\s+(?P<dist>(?:\d+(?:\s\d/\d+)?|About\s+\d+[^\s]*)\s+(?:Furlongs?|Miles?|Yards)(?:\s+\d+/\d+)?)\s*(?P<surf>\(T\))?\s+(?P<age>\S+)(?:,\s*(?P<sex>F & M|F|C & G))?\s+[A-Z][a-z]+day", hc)
        if m:
            race["class_text"] = m.group("cls").strip()
            race["distance_text"] = m.group("dist").strip()
            race["surface"] = "turf" if m.group("surf") else "dirt"
            race["age_text"] = m.group("age")
            race["sex_text"] = m.group("sex")
        else:
            race["class_text"] = hc
            race["distance_text"] = None
            race["surface"] = "turf" if "(T)" in hc else "dirt"
            race["age_text"] = None
            race["sex_text"] = None
        race["distance_furlongs"] = distance_text_to_furlongs(race["distance_text"]) if race["distance_text"] else None
        race["is_route"] = (race["distance_furlongs"] or 0) >= 8.0
        ct = race["class_text"] or ""
        race["class_code"] = classify_race_type(ct)
        mm = re.search(r"(\d{4,6})", ct.replace(",", ""))
        race["claiming_price"] = int(mm.group(1)) if mm and race["class_code"] in ("MCL", "CLM", "OC") else None

    # ------------------------------------------------------------ horses
    def _parse_horses(self, body: list[Row], race: dict):
        # Horse anchors: rows containing the token "Power:" at x ~ 300-345 (not the top-3 box)
        anchors = []
        for i, r in enumerate(body):
            toks = r.tokens(300, 350)
            if any(t["text"].startswith("Power") for t in toks):
                anchors.append(i)
        # Horses with no Prime Power (e.g. foreign import w/o rating) have "Life:" on the name row;
        # detect name rows by the "(style pts)" pattern in x 36..170 instead.
        name_rows = []
        for i, r in enumerate(body):
            t = r.text(36, 175)
            if re.search(r"\((?:E/P|E|P|S|NA)\s+\d\)", t):
                name_rows.append(i)
        starts = sorted(set(name_rows) | set(anchors))
        # dedupe anchors that are adjacent rows (claim price row 2pt above name row)
        dedup = []
        for i in starts:
            if dedup and abs(body[i].top - body[dedup[-1]].top) < 4 and body[i].page == body[dedup[-1]].page:
                continue
            dedup.append(i)
        starts = dedup
        for k, si in enumerate(starts):
            ei = starts[k + 1] if k + 1 < len(starts) else len(body)
            # include a row immediately above if it is the claiming-price/Prime Power row of this horse
            s0 = si
            if si > 0 and abs(body[si - 1].top - body[si].top) < 4 and body[si - 1].page == body[si].page:
                s0 = si - 1
            block = body[s0:ei]
            # drop trailing copyright row
            block = [r for r in block if "Copyright" not in r.text(30, 80)]
            try:
                horse = self._parse_horse_block(block, race)
            except Exception as e:  # keep going; record the failure
                self.warn(f"race {race['race_no']} horse block at page {block[0].page} top {block[0].top:.0f}: {e!r}")
                continue
            if horse:
                race["horses"].append(horse)

    # ------------------------------------------------------------ one horse
    def _parse_horse_block(self, block: list[Row], race: dict) -> dict | None:
        rows = merge_rows(block, 2.6)
        horse: dict = {
            "pgm": None, "post": None, "entry_status": None, "apprentice_allowance": 0, "ml_odds": None, "ml_decimal": None, "name": None, "run_style": None, "speed_pts": None,
            "name_flag": None, "claim_price": None, "color": None, "sex": None, "age": None, "foal_month": None,
            "sale": None, "prime_power": None, "prime_power_rank": None, "owner": None, "silks": None,
            "sire": None, "sire_sire": None, "stud_fee": None, "dam": None, "dam_sire": None, "breeder": None,
            "bred_state": None, "trainer": None, "trainer_meet": None, "jockey": None, "jockey_meet": None,
            "weight": None, "lasix": None, "first_lasix": False, "blinkers_change": None,
            "records": {}, "pedigree_ratings": {}, "jockey_stats": [], "trainer_stats": [], "pedigree_stats": {},
            "positives": [], "negatives": [], "pp": [], "workouts": [],
        }
        # ---- locate section rows
        hdr_idx = next((i for i, r in enumerate(rows) if r.text(5, 60).startswith("DATE TRK")), None)
        if hdr_idx is None:
            # horse with no past performances (first-time starter) -> there is still a header row normally
            hdr_idx = len(rows)
        head = rows[:hdr_idx]
        tail = rows[hdr_idx + 1:] if hdr_idx < len(rows) else []

        # ---- name row
        name_row = None
        for r in head:
            t = r.text(36, 320)
            if re.search(r"\((?:E/P|E|P|S|NA)\s+\d\)", t):
                name_row = r
                break
        if name_row is None:
            raise ParseError("no name row")
        self._parse_name_row(name_row, horse)

        # ---- left column: pgm / ML odds / jockey
        for r in head:
            t = r.text(0, 36)
            mpg = re.fullmatch(r"(\d{1,2}[A-Z]?)(?:pp(\d{1,2}))?", t.replace(" ", ""))
            if horse["pgm"] is None and mpg:
                horse["pgm"] = mpg.group(1)
                horse["post"] = int(mpg.group(2)) if mpg.group(2) else (int(re.sub(r"[A-Z]", "", mpg.group(1))) if mpg.group(1)[0].isdigit() else None)
            m = re.match(r"^(\d+)/(\d+)$", t)
            if m:
                horse["ml_odds"] = t
                horse["ml_decimal"] = round(int(m.group(1)) / int(m.group(2)), 3)
            tj = r.text(0, 190)
            mj = re.match(r"^([A-Z][A-Z' .,-]+?)\s*\((\d+)\s+(\d+)-(\d+)-(\d+)\s+(\d+)%\)", tj)
            if mj and r.x_min < 12:
                horse["jockey"] = mj.group(1).strip().title()
                horse["jockey_meet"] = {"starts": int(mj.group(2)), "win": int(mj.group(3)), "place": int(mj.group(4)),
                                        "show": int(mj.group(5)), "win_pct": int(mj.group(6))}
        # ---- middle column: owner / silks / sire / dam / breeder / trainer / equipment / weight
        for r in head:
            t = r.text(36, 198)
            if re.search(r"\b(AE|MTO)\b", t):
                horse["entry_status"] = re.search(r"\b(AE|MTO)\b", t).group(1)
                t = re.sub(r"\s*\b(AE|MTO)\b\s*", " ", t).strip()
            if t.startswith("Own:"):
                horse["owner"] = t[4:].strip()
            elif horse["owner"] and horse["silks"] is None and r.text(0, 36) and re.match(r"^\d+/\d+$", r.text(0, 36)):
                horse["silks"] = t
            tm = r.text(198, 360)
            if tm.startswith("Sire"):
                s = re.sub(r"^Sire\s*:\s*", "", tm)
                m = re.match(r"^(.+?)\s*\((.+)\)\s*(?:\$([\d,]+))?\s*$", s)
                if m:
                    horse["sire"] = m.group(1).strip()
                    horse["sire_sire"] = m.group(2).strip()
                    horse["stud_fee"] = num(m.group(3)) if m.group(3) else None
                else:
                    horse["sire"] = s
            elif tm.startswith("Dam:"):
                s = tm[4:].strip()
                m = re.match(r"^(.+?)\s*\((.+)\)\s*$", s)
                if m:
                    horse["dam"] = m.group(1).strip()
                    horse["dam_sire"] = m.group(2).strip()
                else:
                    horse["dam"] = s
            elif tm.startswith("Brdr:"):
                s = tm[5:].strip()
                m = re.match(r"^(.+?)\s*\(([A-Za-z]+)\)\s*$", s)
                if m:
                    horse["breeder"] = m.group(1).strip()
                    horse["bred_state"] = m.group(2)
                else:
                    horse["breeder"] = s
            elif tm.startswith("Trnr:"):
                s = tm[5:].strip()
                m = re.match(r"^(.+?)\s*\((\d+)\s+(\d+)-(\d+)-(\d+)\s+(\d+)%\)", s)
                if m:
                    horse["trainer"] = m.group(1).strip()
                    horse["trainer_meet"] = {"starts": int(m.group(2)), "win": int(m.group(3)), "place": int(m.group(4)),
                                             "show": int(m.group(5)), "win_pct": int(m.group(6))}
                else:
                    horse["trainer"] = s
            te = r.text(355, 393)
            if "Blnkr" in te:
                horse["blinkers_change"] = "on" if "On" in te else "off"
            if SYM_FIRST_LASIX in te:
                horse["first_lasix"] = True
            mw = re.search(r"\b(L)?\s*(\d{3})(" + SUP_CLASS + r"+)?", te.replace(SYM_FIRST_LASIX, ""))
            if mw and 100 <= int(mw.group(2)) <= 135:
                horse["weight"] = int(mw.group(2))
                horse["apprentice_allowance"] = sup_to_int(mw.group(3)) if mw.group(3) else 0
                horse["lasix"] = bool(mw.group(1))
            elif re.search(r"\bL\b", te):
                horse["lasix"] = True
        # ---- right column: records
        for r in head:
            left = r.text(392, 487)
            right = r.text(487, 612)
            if left:
                m = re.match(r"^(Life:|DMR|[A-Z]{2,4}|\d{4})\s*(.*)$", left)
                if m:
                    key = m.group(1).rstrip(":")
                    rec = parse_record(m.group(2))
                    if rec:
                        if key == "Life":
                            horse["records"]["life"] = rec
                        elif re.fullmatch(r"\d{4}", key):
                            horse["records"][f"year_{key}"] = rec
                        else:
                            horse["records"]["track"] = rec
                            horse["records"]["track_code"] = key
            if right:
                m = re.match(r"^(Fst|Off|Dis|Trf|AW)\s*(?:\(([^)]*)\))?\s*(.*)$", right)
                if m:
                    key = m.group(1).lower()
                    if m.group(2) is not None:
                        horse["pedigree_ratings"][key] = m.group(2)
                    rec = parse_record(m.group(3))
                    if rec:
                        horse["records"][key] = rec
        # ---- jockey / trainer / pedigree stats and bullets
        in_stats = False
        pos_txt, neg_txt = [], []
        for r in head:
            tl = r.text(5, 190)
            if re.match(r"^(\d{4}|JKYw/)", tl) and r.x_min < 15:
                in_stats = True
                m = re.match(r"^(?P<cat>.+?)\s+(?P<n>\d+)\s+(?P<w>\d+)%\s+(?P<itm>\d+)%\s+(?P<roi>[+-]?\d+\.\d+)\s*$", tl)
                if m:
                    horse["jockey_stats"].append({"category": m.group("cat"), "starts": int(m.group("n")), "win_pct": int(m.group("w")),
                                                  "itm_pct": int(m.group("itm")), "roi": float(m.group("roi"))})
            tt = r.text(190, 392)
            if in_stats and tt:
                m = re.match(r"^(?P<flag>\+)?\s*(?P<cat>.+?)\s+(?P<n>\d+)\s+(?P<w>\d+)%\s+(?P<itm>\d+)%\s+(?P<roi>[+-]?\d+\.\d+)\s*$", tt)
                if m:
                    horse["trainer_stats"].append({"category": m.group("cat").strip(), "flag": bool(m.group("flag")), "starts": int(m.group("n")),
                                                   "win_pct": int(m.group("w")), "itm_pct": int(m.group("itm")), "roi": float(m.group("roi"))})
            tp = r.text(392, 612)
            if in_stats and tp:
                self._parse_pedigree_stats(tp, horse["pedigree_stats"])
            full = r.text()
            if SYM_POS in full or SYM_NEG in full:
                pos_txt.append(r.text(0, 306))
                neg_txt.append(r.text(306, 612))
        horse["positives"] = split_bullets(" ".join(pos_txt), SYM_POS) + split_bullets(" ".join(pos_txt), SYM_NEG)
        horse["negatives"] = split_bullets(" ".join(neg_txt), SYM_NEG) + split_bullets(" ".join(neg_txt), SYM_POS)

        # ---- past performances & workouts
        for r in tail:
            t = r.text(0, 60)
            if r.x_min < 15 and DATE_RE.match(t):
                pp = self._parse_pp_row(r)
                if pp:
                    horse["pp"].append(pp)
            elif r.x_min < 15 and re.match(r"^" + re.escape(SYM_NEG) + r"?\d{2}[A-Z][a-z]{2}(?:'\d{2})?\s", r.text()):
                horse["workouts"].extend(self._parse_workouts(r.text()))
        # derived
        horse["days_since_last"] = None
        if horse["pp"] and race.get("race_date_iso"):
            pass
        return horse

    def _derive_horse_fields(self, h: dict, race: dict):
        from datetime import date as _date
        try:
            today = _date.fromisoformat(self.card["date"]) if self.card.get("date") else None
        except ValueError:
            today = None
        h["days_since_last"] = None
        if h["pp"] and today:
            try:
                last = _date.fromisoformat(h["pp"][0]["date"])
                h["days_since_last"] = (today - last).days
            except ValueError:
                pass
        # merge race-summary row (if the summary page was parsed) by program number
        summ = {e["pgm"]: e for e in (race.get("summary") or [])}
        h["summary"] = summ.get(h["pgm"])
        if h["summary"] and h["summary"].get("days_since") is not None:
            h["days_since_last"] = h["summary"]["days_since"]
        # workouts since last race
        h["lifetime_starts"] = (h["records"].get("life") or {}).get("starts", len(h["pp"]))
        h["first_time_starter"] = h["lifetime_starts"] == 0

    # ------------------------------------------------------------ name row
    def _parse_name_row(self, r: Row, horse: dict):
        t = r.text(36, 310)
        m = re.match(
            r"^(?P<name>.+?)\s*\((?P<style>E/P|E|P|S|NA)\s+(?P<pts>\d)\)\s*(?P<flag>" + re.escape(SYM_NAME_FLAG) + r")?\s*"
            r"(?:\$(?P<claim>[\d,]+))?\s*(?P<rest>.*)$", t)
        if not m:
            raise ParseError(f"name row unparsed: {t!r}")
        horse["name"] = clean_name(m.group("name"))
        horse["run_style"] = m.group("style")
        horse["speed_pts"] = int(m.group("pts"))
        horse["name_flag"] = m.group("flag")
        horse["claim_price"] = num(m.group("claim")) if m.group("claim") else None
        rest = m.group("rest")
        mc = re.match(r"^(?P<color>[A-Za-z/]+)\.\s*(?P<sex>[a-z])\.\s*(?P<age>\d+)\s*(?:\((?P<month>[A-Za-z]+)\))?\s*(?P<sale>.*)$", rest)
        if mc:
            horse["color"] = mc.group("color")
            horse["sex"] = mc.group("sex")
            horse["age"] = int(mc.group("age"))
            horse["foal_month"] = mc.group("month")
            sale = mc.group("sale").strip()
            if sale:
                horse["sale"] = sale
        tp = r.text(300, 400)
        mp = re.search(r"Prime Power:\s*([\d.]+)\s*\((\d+)[a-z]{2}\)", tp)
        if mp:
            horse["prime_power"] = float(mp.group(1))
            horse["prime_power_rank"] = int(mp.group(2))

    # ------------------------------------------------------------ pedigree stats
    def _parse_pedigree_stats(self, t: str, out: dict):
        if t.startswith("Sire Stats:") or t.startswith("Dam'sSire:"):
            key = "sire" if t.startswith("Sire") else "dam_sire"
            m = re.search(r"AWD\s*([\d.]+)\s*(\d+)%Mud\s*(\d+)MudSts\s*(\d+)%1st\s*([\d.]+)spi", t)
            if m:
                out[key] = {"awd": float(m.group(1)), "mud_pct": int(m.group(2)), "mud_starts": int(m.group(3)),
                            "first_pct": int(m.group(4)), "spi": float(m.group(5))}
        elif t.startswith("Dam'sStats:"):
            m = re.search(r"Dam'sStats:\s*(\S+)\s*(\d+)%2yo\s*(\d+)str\s*(\d+)w\s*(\d+)sw\s*([\d.]+)dpi", t)
            if m:
                out["dam"] = {"status": m.group(1), "two_yo_pct": int(m.group(2)), "starters": int(m.group(3)),
                              "winners": int(m.group(4)), "stakes_winners": int(m.group(5)), "dpi": float(m.group(6))}
        elif t.startswith("SoldAt:"):
            m = re.search(r"SoldAt:\s*(.+?)\s*SireAvg:\s*\$?([\d.]+k?)\s*StudFee:\s*\$?([\d,]+)", t)
            if m:
                out["sold_at"] = m.group(1).strip()
                out["sire_avg"] = m.group(2)
                out["stud_fee"] = num(m.group(3))

    # ------------------------------------------------------------ PP row
    def _parse_pp_row(self, r: Row) -> dict | None:
        c = {k: r.text(a, b) for k, (a, b) in PP_COLS.items()}
        pp: dict = {"raw": r.text()}
        left = r.text(0, 147.5)
        # ---- date / track / race number
        m = DATE_RE.match(c["date_trk"])
        dd, mon, yy = m.group(1), m.group(2), m.group(3)
        pp["date"] = f"20{yy}-{MONTHS.get(mon, 0):02d}-{dd}"
        foreign = re.match(r"^\d{2}[A-Z][a-z]{2}\d{2}\s+(?P<trk>[A-Za-z .]+\([A-Za-z]+\))\s*(?P<rest>.*)$", left)
        if foreign:
            pp["track"] = foreign.group("trk").strip()
            pp["race_no"] = None
            pp["foreign"] = True
            dist_txt = foreign.group("rest")
        else:
            mt = re.match(r"^\d{2}[A-Z][a-z]{2}\d{2}\s*(?P<trk>[A-Za-z]+)\s*(?P<rn>" + SUP_CLASS + r"+)?", c["date_trk"])
            pp["track"] = mt.group("trk") if mt else None
            pp["race_no"] = sup_to_int(mt.group("rn")) if mt and mt.group("rn") else None
            pp["foreign"] = (pp["track"] in FOREIGN_TRACK_CODES)
            dist_txt = c["dist"]
        # ---- surface / distance / condition
        surf = "dirt"
        if SYM_TURF in dist_txt:
            surf = "turf"
        elif SYM_AW in dist_txt:
            surf = "aw"
        pp["surface"] = surf
        dtxt = dist_txt.replace(SYM_TURF, " ").replace(SYM_AW, " ")
        pp["about_or_alt_course"] = "*" in dtxt
        dtxt = dtxt.replace("*", " ")
        my = re.search(r"(" + SUP_CLASS + r"{3})\s*([a-z]{2,3})?", dtxt)
        md = re.search(r"(\d+[fmˆ„‰‚½]?)\s*([a-z]{2,3})?", dtxt)
        if my:  # distance given in yards (Quarter-Horse style, e.g. 870y at Los Alamitos)
            yards = sup_to_int(my.group(1))
            pp["distance_furlongs"] = round(yards / 220.0, 2)
            pp["distance_text"] = f"{yards}y"
            pp["track_condition"] = my.group(2) if my.group(2) in TRACK_CONDITIONS else None
        elif md:
            fur, dlabel = parse_distance(md.group(1))
            pp["distance_furlongs"] = fur
            pp["distance_text"] = dlabel
            pp["track_condition"] = md.group(2) if md.group(2) in TRACK_CONDITIONS else None
        else:
            pp["distance_furlongs"] = None
            pp["distance_text"] = None
            pp["track_condition"] = None
        if foreign and pp["track_condition"] is None:
            mc = re.search(r"\b(ft|gd|my|sy|fm|yl|sf|hy|sl)\b", left)
            pp["track_condition"] = mc.group(1) if mc else None
        # ---- fractions and final time
        times_txt = c["times"] if not foreign else foreign.group("rest")
        tlist = re.findall(r"(?:\d+:)?\d\d" + SUP_CLASS + r"?", times_txt)
        times = [parse_time(x) for x in tlist]
        pp["fractions"] = times[:-1] if len(times) > 1 else []
        pp["final_time"] = times[-1] if times else None
        # ---- age restriction symbol, race rating, race type, class rating
        age_txt = r.text(147.5, 156)
        pp["age_restriction"] = "3up" if SYM_AGE_3UP in age_txt else ("4up" if SYM_AGE_4UP in age_txt else "age_specific")
        pp["race_rating"] = sup_to_int(c["rr"])
        rt = c["racetype"]
        pp["race_type_raw"] = rt
        pp["fillies_mares"] = SYM_FILLIES in rt
        pp["state_bred"] = SYM_STATEBRED in rt
        rtc = clean_name(rt).replace(" ", "")
        pp["race_type"] = rtc
        pp["class_code"] = classify_race_type(rtc)
        pp["claimed"] = rtc.endswith("-c")
        mcl = re.search(r"(\d{4,6})", rtc.replace("k", "000") if re.search(r"\d+k", rtc) else rtc)
        pp["race_purse_or_price"] = int(mcl.group(1)) if mcl else None
        pp["class_rating"] = sup_to_int(c["cr"])
        # ---- pace / speed figures
        figs = r.text(214.5, 253)
        mf = re.match(r"^\s*(?:(?P<e1>\d+)\s+)?(?P<e2>\d+)\s*/\s*(?P<lp>\d+)?\s*$", figs)
        if mf:
            pp["e1"], pp["e2"], pp["lp"] = num(mf.group("e1")), num(mf.group("e2")), num(mf.group("lp"))
        else:
            pp["e1"], pp["e2"], pp["lp"] = None, None, None
        cc = re.findall(r"[+-]?\d+", r.text(253, 279.5))
        pp["c1"] = int(cc[0]) if len(cc) >= 1 else None
        pp["c2"] = int(cc[1]) if len(cc) >= 2 else None
        if len(cc) == 1:
            # a lone value: decide by position
            tk = r.tokens(253, 279.5)
            if tk and tk[0]["x0"] >= 265:
                pp["c1"], pp["c2"] = None, int(cc[0])
        sp = r.tokens(279.5, 299)
        pp["speed"], pp["post"] = None, None
        for tk in sp:
            if re.fullmatch(r"-?\d+", tk["text"]):
                if tk["x0"] >= 291.5 and not tk["text"].startswith("-"):
                    pp["post"] = int(tk["text"])
                else:
                    pp["speed"] = int(tk["text"])
        # ---- calls
        pp["start"] = parse_call(c["st"])
        pp["call1"] = parse_call(c["call1"])
        pp["call2"] = parse_call(c["call2"])
        pp["stretch"] = parse_call(c["str"])
        pp["finish"] = parse_call(c["fin"])
        # ---- jockey / weight
        jt = r.text(374, 421.5)
        mj = re.match(r"^(?P<name>[A-Za-z'\-]+?)(?P<wt>" + SUP_CLASS + r"{3})(?P<app>\*{1,3})?(?P<x>[A-Za-z]*)$", jt.replace(" ", ""))
        if mj:
            pp["jockey"] = mj.group("name")
            pp["weight"] = sup_to_int(mj.group("wt"))
            pp["apprentice"] = len(mj.group("app")) if mj.group("app") else 0
        else:
            pp["jockey"] = clean_name(jt)
            pp["weight"] = sup_to_int(jt)
            pp["apprentice"] = 0
        # ---- medication/equipment
        med = c["med"]
        pp["lasix"] = "L" in med
        pp["blinkers"] = "b" in med
        pp["front_wraps"] = "f" in med
        pp["med_equip_raw"] = med
        # ---- odds
        ot = c["odds"]
        mo = re.match(r"^(\*)?(\d+\.\d+)(e)?", ot)
        pp["favorite"] = bool(mo and mo.group(1))
        pp["odds"] = float(mo.group(2)) if mo else None
        pp["coupled_entry"] = bool(mo and mo.group(3))
        # ---- top finishers / comment / field size
        toks = r.tokens(450.5, 700)
        finishers, comment, fieldsize = [], [], None
        if toks and re.fullmatch(r"\d{1,2}", toks[-1]["text"]) and toks[-1]["x0"] >= 600:
            fieldsize = int(toks[-1]["text"])
            toks = toks[:-1]
        split = len(toks)
        for i in range(1, len(toks)):
            if toks[i]["x0"] - toks[i - 1]["x1"] > 4.5:
                split = i
                break
        finishers = toks[:split]
        comment = toks[split:]
        pp["field_size"] = fieldsize
        pp["top_finishers_raw"] = " ".join(t["text"] for t in finishers)
        pp["top_finishers"] = parse_finishers(pp["top_finishers_raw"])
        pp["comment"] = " ".join(t["text"] for t in comment)
        # derived
        fin = pp["finish"]
        pp["finish_pos"] = fin["pos"]
        pp["beaten_lengths"] = fin["lengths"] if fin["pos"] and fin["pos"] > 1 else (0.0 if fin["pos"] == 1 else None)
        pp["won"] = fin["pos"] == 1
        pp["dnf"] = (fin["raw"] == "-")
        pp["is_route"] = (pp["distance_furlongs"] or 0) >= 8.0
        return pp

    # ------------------------------------------------------------ workouts
    def _parse_workouts(self, t: str) -> list[dict]:
        out = []
        for m in WORK_RE.finditer(t):
            out.append({
                "date": m.group("date"), "track": m.group("trk"), "turf": bool(m.group("turf")),
                "distance_furlongs": float(m.group("dist")[:-1]), "condition": m.group("cond"),
                "time": parse_time(m.group("time")), "type": m.group("type"), "rank": int(m.group("rank")), "of": int(m.group("of")),
                "bullet": bool(m.group("bullet")) or int(m.group("rank")) == 1,
            })
        return out

    # ------------------------------------------------------------ summary page
    def _parse_summary_page(self, body: list[Row], race: dict):
        rows = body
        # racetype stats
        for i, r in enumerate(rows):
            if "RACETYPE STATS" in r.text():
                for rr in rows[i + 1:i + 3]:
                    t = rr.text()
                    m = re.match(r"^(?P<desc>.+?)\s+(?P<races>\d+)\s+(?P<win>\d+)%\s+(?P<itm>\d+)%\s+(?P<roi>[+-]?\d+\.\d+)\s+(?P<fs>[\d.]+)\s+\$(?P<pay>[\d.]+)\s+(?P<a>\d+)%\s+(?P<b>\d+)%\s+(?P<c>\d+)%", t)
                    if m:
                        race["racetype_stats"] = {"description": m.group("desc"), "races": int(m.group("races")), "fav_win_pct": int(m.group("win")),
                                                  "fav_itm_pct": int(m.group("itm")), "fav_roi": float(m.group("roi")), "avg_field_size": float(m.group("fs")),
                                                  "median_win_payoff": float(m.group("pay")), "pct_winners_lt_5_1": int(m.group("a")),
                                                  "pct_winners_5_to_10_1": int(m.group("b")), "pct_winners_gt_10_1": int(m.group("c"))}
                break
        # track bias
        race["bias"] = {"meet": self._parse_bias(rows, 0, 315), "week": self._parse_bias(rows, 315, 612)}
        # race summary table
        hdr = next((i for i, r in enumerate(rows) if r.text(0, 100).startswith("# Horse Name")), None)
        summ = []
        if hdr is not None:
            for r in rows[hdr + 1:]:
                if r.top - rows[hdr].top > 300 or r.text().startswith("Average") or "Speed Last Race" in r.text(0, 90):
                    break
                left = r.text(0, 100)
                m = re.match(r"^(?P<pgm>\d{1,2}[A-Z]?)\s*(?P<name>.+?)\s*(?P<ml>\d+/\d+)(?P<fl>" + re.escape(SYM_FIRST_LASIX) + r")?$", left)
                if not m:
                    continue
                spd_avg = r.text(207, 232)
                entry = {
                    "pgm": m.group("pgm"), "name": clean_name(m.group("name")), "ml_odds": m.group("ml"),
                    "first_lasix": bool(m.group("fl")) or SYM_FIRST_LASIX in left,
                    "equipment": r.text(100, 116), "days_since_raw": r.text(116, 136),
                    "run_style_raw": r.text(136, 158), "speed_pts": num(r.text(158, 168)),
                    "avg_e1": num(r.text(168, 183)), "avg_e2": num(r.text(183, 196).replace("/", "")), "avg_late": num(r.text(196, 207)),
                    "avg_spd_raw": spd_avg, "avg_spd": num(re.sub(r"[()*\s]", "", spd_avg)),
                    "avg_spd_flag": "paren" if "(" in spd_avg else ("star" if "*" in spd_avg else None),
                    "avg_race_rating": num(r.text(232, 257)),
                    "best_e1": num(r.text(257, 271)), "best_e2": num(r.text(271, 288).replace("/", "")), "best_late": num(r.text(288, 305)),
                    "sp1_raw": r.text(305, 322), "sp2_raw": r.text(322, 340), "sp3_raw": r.text(340, 357), "sp4_raw": r.text(357, 376),
                    "acl_raw": r.text(376, 400), "rcg_spd_avg": num(r.text(400, 418)),
                    "r1": num(r.text(418, 436)), "r2": num(r.text(436, 454)), "r3": num(r.text(454, 472)),
                    "ped_spd": num(r.text(472, 488)), "ped_mud": num(r.text(488, 506)), "ped_first": num(r.text(506, 521)),
                    "ped_spi": num(r.text(521, 541)), "ped_dpi": num(r.text(541, 561)), "sire_awd": num(r.text(561, 580)), "damsire_awd": num(r.text(580, 612)),
                }
                ds = entry["days_since_raw"]
                md = re.match(r"^(\d+)(\.*)$", ds)
                entry["days_since"] = int(md.group(1)) if md else None
                entry["races_since_layoff"] = len(md.group(2)) if md else None
                rs = entry["run_style_raw"]
                mr = re.match(r"^(\+*)\s*(E/P|E|P|S|NA)$", rs)
                entry["bias_plus"] = len(mr.group(1)) if mr else 0
                entry["run_style"] = mr.group(2) if mr else rs or None
                for k in ("sp1", "sp2", "sp3", "sp4"):
                    raw = entry[k + "_raw"]
                    mm = re.match(r"^(\d+)([T.]*)$", raw)
                    entry[k] = int(mm.group(1)) if mm else None
                    entry[k + "_turf"] = bool(mm and "T" in mm.group(2))
                    entry[k + "_route"] = bool(mm and "." in mm.group(2))
                acl = entry["acl_raw"]
                entry["acl"] = num(re.sub(r"[()\s]", "", acl))
                entry["acl_paren"] = "(" in acl
                summ.append(entry)
        race["summary"] = summ
        # rankings
        rk = next((i for i, r in enumerate(rows) if r.text(0, 90).startswith("Speed Last Race") and r.text(90, 170).startswith("Back")), None)
        rankings = {k: [] for k in ("speed_last_race", "back_speed", "current_class", "class_last_3", "prime_power", "early_pace_last", "late_pace_last")}
        cols = [("speed_last_race", 0, 88), ("back_speed", 88, 170), ("current_class", 170, 255), ("class_last_3", 255, 340),
                ("prime_power", 340, 430), ("early_pace_last", 430, 515), ("late_pace_last", 515, 612)]
        if rk is not None:
            for r in rows[rk + 1:]:
                if "Copyright" in r.text():
                    break
                for k, a, b in cols:
                    t = r.text(a, b)
                    m = re.match(r"^(NA|[\d.]+)\s+(.+)$", t)
                    if m:
                        rankings[k].append({"value": num(m.group(1)), "name": clean_name(m.group(2))})
        race["rankings"] = rankings

    def _parse_bias(self, rows: list[Row], a: float, b: float) -> dict:
        out: dict = {}
        centers = None
        for i, r in enumerate(rows):
            t = r.text(a, b)
            if re.match(r"^(Dirt|Turf|AW|All Weather)\s+[\d.]+f", t):
                m = re.match(r"^(\w+)\s+([\d.]+)f", t)
                out["surface"] = m.group(1)
                out["distance_furlongs"] = float(m.group(2))
                m = re.search(r"Speed Bias:\s*(\d+)%", t)
                out["speed_bias_pct"] = int(m.group(1)) if m else None
            elif t.startswith("# Races:"):
                m = re.search(r"# Races:\s*(\d+)", t)
                out["races"] = int(m.group(1)) if m else None
                m = re.search(r"(\d\d/\d\d)\s*-\s*(\d\d/\d\d)", t)
                out["period"] = f"{m.group(1)}-{m.group(2)}" if m else None
                m = re.search(r"1stCall:\s*([\d.]+)", t)
                out["winner_avg_bl_1st_call"] = float(m.group(1)) if m else None
            elif t.startswith("%Wire:"):
                m = re.search(r"%Wire:\s*(\d+)%", t)
                out["wire_pct"] = int(m.group(1)) if m else None
                m = re.search(r"2ndCall:\s*([\d.]+)", t)
                out["winner_avg_bl_2nd_call"] = float(m.group(1)) if m else None
            elif t.startswith("Runstyle:"):
                toks = r.tokens(a, b)
                labels = [tk for tk in toks if tk["text"] in ("E", "E/P", "P", "S")]
                centers = [(tk["x0"] + tk["x1"]) / 2 for tk in labels]
                out["runstyle"] = {lab["text"]: {"marks": 0, "impact": None, "win_pct": None} for lab in labels}
                # marks row, impact row, win row follow
                sect = out["runstyle"]
                keys = [lab["text"] for lab in labels]
                self._fill_bias_rows(rows, i, a, b, centers, keys, sect)
            elif t.startswith("Post Bias:"):
                toks = r.tokens(a, b)
                labels = [tk for tk in toks if tk["text"] in ("RAIL", "1-3", "4-7", "8+")]
                centers = [(tk["x0"] + tk["x1"]) / 2 for tk in labels]
                out["post"] = {lab["text"]: {"marks": 0, "impact": None, "win_pct": None} for lab in labels}
                keys = [lab["text"] for lab in labels]
                self._fill_bias_rows(rows, i, a, b, centers, keys, out["post"])
        return out

    def _fill_bias_rows(self, rows, i, a, b, centers, keys, sect):
        def nearest(x):
            return keys[min(range(len(centers)), key=lambda k: abs(centers[k] - x))]
        for rr in rows[i + 1:i + 5]:
            t = rr.text(a, b)
            toks = rr.tokens(a, b)
            if t.startswith("Impact"):
                vals = [tk for tk in toks if re.fullmatch(r"[\d.]+", tk["text"])]
                for tk in vals:
                    sect[nearest((tk["x0"] + tk["x1"]) / 2)]["impact"] = float(tk["text"])
            elif t.startswith("%Races") or t.startswith("Avg Win"):
                vals = [tk for tk in toks if re.fullmatch(r"\d+%", tk["text"])]
                for tk in vals:
                    sect[nearest((tk["x0"] + tk["x1"]) / 2)]["win_pct"] = int(tk["text"][:-1])
            elif all(re.fullmatch(r"\+{1,3}", tk["text"]) for tk in toks) and toks:
                for tk in toks:
                    sect[nearest((tk["x0"] + tk["x1"]) / 2)]["marks"] = len(tk["text"])


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def split_bullets(text: str, sym: str) -> list[str]:
    parts = [p.strip() for p in text.split(sym)]
    out = []
    for p in parts[1:]:
        # a chunk may still contain the *other* symbol; cut there
        p = re.split(r"[" + re.escape(SYM_POS + SYM_NEG) + r"]", p)[0].strip()
        if p:
            out.append(p)
    return out


def parse_finishers(raw: str) -> list[dict]:
    """
    'GoldnHopƒAstrnmcalyƒVlvtRign¨' -> [{'name':'GoldnHop','margin':0.75}, ...]
    Names are abbreviated by Brisnet; the margin following each name is that
    horse's margin over the next finisher.
    """
    out = []
    pat = re.compile(r"(?P<name>[^" + re.escape("".join("\u0081‚ƒ±²³´")) + SUP_CLASS[1:-1] + r"]+)(?P<marg>(?:" + SUP_CLASS + r"+)?" + FRAC_CLASS + r"?" + MARGIN_CLASS + r"?)")
    for m in pat.finditer(raw):
        name = m.group("name").strip()
        if not name:
            continue
        call = parse_call(m.group("marg")) if m.group("marg") else {"lengths": None, "margin": None}
        out.append({"name": name, "margin_lengths": call.get("lengths"), "margin": call.get("margin")})
    return out[:3]


def classify_race_type(rt: str) -> str:
    s = rt.replace(" ", "")
    if re.match(r"^MC\d", s) or s.startswith("MCL") or s.startswith("MC"):
        return "MCL"
    if s.startswith("Mdn") or s.startswith("Msw") or s.startswith("MSW"):
        return "MSW"
    if s.startswith("Moc") or s.startswith("MOC"):
        return "MOC"
    if s.startswith("OC") or re.match(r"^A\d", s):
        return "OC"
    if s.startswith("Clm") or re.match(r"^C\d", s) or re.match(r"^’?C\d", s):
        return "CLM"
    if s.startswith("Alw") or s.startswith("A"):
        return "ALW"
    if s.startswith("Stk") or re.search(r"-G\d", s) or s.endswith("G1") or s.endswith("G2") or s.endswith("G3"):
        return "STK"
    if "Hcp" in s:
        return "HCP"
    if s.startswith("Str") or s.startswith("Starter"):
        return "STR"
    if re.search(r"[A-Za-z]+\d+k", s) or re.search(r"B\d+K", s) or re.search(r"\d+K$", s):
        return "STK"
    return "OTHER"


def distance_text_to_furlongs(t: str) -> float | None:
    t = t.strip()
    half = "\u00bd" in t
    t = t.replace("\u00bd", "")
    m = re.match(r"^(?:About\s+)?(\d+)(?:\s+(\d)/(\d+))?\s*(Furlongs?|Miles?|Yards)(?:\s+(\d+)/(\d+))?", t)
    if not m:
        return None
    n = int(m.group(1))
    frac = 0.5 if half else 0.0
    if m.group(2):
        frac = int(m.group(2)) / int(m.group(3))
    elif m.group(5):
        frac = int(m.group(5)) / int(m.group(6))
    unit = m.group(4)
    if unit.startswith("Furlong"):
        return n + frac
    if unit.startswith("Mile"):
        return (n + frac) * 8.0
    if unit.startswith("Yard"):
        return n / 220.0
    return None


def parse_pdf(path: str, verbose: bool = False) -> dict:
    return BrisnetPPParser(path, verbose=verbose).parse()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Parse a Brisnet Ultimate PPs PDF to JSON")
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", help="output JSON path (default: stdout)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    card = parse_pdf(args.pdf, verbose=args.verbose)
    s = json.dumps(card, indent=1, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(s)
        print(f"wrote {args.out}: {len(card['races'])} races, {sum(len(r['horses']) for r in card['races'])} horses, "
              f"{sum(len(h['pp']) for r in card['races'] for h in r['horses'])} PP lines, {len(card['warnings'])} warnings")
    else:
        print(s)
