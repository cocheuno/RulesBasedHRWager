"""
Read a track payout-page screenshot (data/results-png/<card>/r<N>.png) into a results-file race entry.

Two layers so the parsing is testable without an OCR engine:
  * ocr_rows(path) -> rows: [(y, [(x, text, conf), ...]), ...]   (engine: RapidOCR, else Tesseract)
  * parse_payout_rows(rows, race_no, roster=None) -> race dict in the results-file format plus an "ocr" block
    with the names read, the confidence, and any warning (finish order from the combos disagrees with the
    names, a pool that could not be read, ...).

Finish order comes from the exotic combinations (superfecta > trifecta > exacta), which OCR reads reliably;
the "PP n" boxes and the runner names are cross-checks.  Win / place / show amounts are assigned by column.

Optional dependency (only for this file):  pip install rapidocr_onnxruntime   (pure pip, no system install)
or a Tesseract install plus  pip install pytesseract.
"""
from __future__ import annotations

import difflib
import re

MONEY = re.compile(r"^\$?\s?(\d{1,3}(?:,\d{3})*|\d+)(?:\.(\d{2}))?$")
POOL_RE = re.compile(r"^\$?\s?(?P<base>\d+(?:\.\d+)?)\s*(?P<pool>EXACTA|EXACTOR|QUINELLA|TRIFECTA|TRIACTOR|SUPERFECTA|SUPER HIGH FIVE|SUPER HI ?5|HI ?5|PENTAFECTA|DOUBLE|DAILY DOUBLE|PICK[- ]?(?P<n>\d)|GRAND SLAM)\b", re.I)
COMBO_RE = re.compile(r"^[\dA-Z]{1,3}(?:[,/][\dA-Z]{1,3})+/?$")
CONSOL_RE = re.compile(r"\(\s*\d+\s*of\s*\d+\s*\)", re.I)
PP_RE = re.compile(r"^P\s?P\s?(\d{1,2}[A-Z]?)$", re.I)
NOISE = re.compile(r"^(PROGRAM|POOLS|PPS|STATS|RESULTS|VIDEO.*|PAYOUTS|FINISH ORDER|VIEW CHART|RUNNER|WIN|PLACE|SHOW|POOL TYPE|RUNNERS|PAYOUT|BET|DE|RA|MY|M|OFFICIAL|ADD TO STABLE|RACE \d+)$", re.I)
COND_RE = re.compile(r"\b(DIRT|TURF|ALL ?WEATHER|SYNTHETIC|TAPETA|AW|INNER TURF|WIDENER)\s*[:\-]\s*([A-Z ]{3,12})\b", re.I)


# ---------------------------------------------------------------------------
# OCR engines
# ---------------------------------------------------------------------------
def ocr_rows(path: str, y_tol: int = 10) -> list[tuple[int, list[tuple[int, str, float]]]]:
    """Text boxes grouped into rows by vertical centre.  Tries RapidOCR, then Tesseract."""
    boxes = None
    try:
        from rapidocr_onnxruntime import RapidOCR
        eng = _rapid_engine()
        res, _ = eng(path)
        boxes = [(int(min(p[0] for p in box)), int(sum(p[1] for p in box) / 4), text, float(conf)) for box, text, conf in (res or [])]
    except ImportError:
        try:
            import pytesseract
            from PIL import Image
            d = pytesseract.image_to_data(Image.open(path), output_type=pytesseract.Output.DICT)
            boxes = []
            # join words on the same line into phrases
            lines: dict[tuple, list] = {}
            for i, t in enumerate(d["text"]):
                if not t.strip():
                    continue
                key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
                lines.setdefault(key, []).append((d["left"][i], d["top"][i] + d["height"][i] // 2, t, float(d["conf"][i]) / 100.0))
            for ws in lines.values():
                ws.sort()
                x, y = ws[0][0], ws[0][1]
                boxes.append((x, y, " ".join(w[2] for w in ws), min(w[3] for w in ws)))
        except ImportError as e:
            raise RuntimeError("no OCR engine: pip install rapidocr_onnxruntime (recommended) or install Tesseract + pip install pytesseract") from e
    rows: dict[int, list] = {}
    for x, y, text, conf in boxes:
        key = min((k for k in rows if abs(k - y) <= y_tol), default=None)
        rows.setdefault(y if key is None else key, []).append((x, text.strip(), conf))
    return [(y, sorted(rows[y])) for y in sorted(rows)]


_ENGINE = None


def _rapid_engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _ENGINE = RapidOCR()
    return _ENGINE


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------
def _money(t: str):
    m = MONEY.match(t.replace(" ", ""))
    if not m:
        return None
    return float(m.group(1).replace(",", "") + "." + (m.group(2) or "00"))


def _norm_pool(name: str, n: str | None) -> str:
    s = name.upper().replace(" ", "").replace("-", "")
    if s.startswith("PICK"):
        return f"PICK{n or s[4:]}"
    return {"EXACTOR": "EXACTA", "TRIACTOR": "TRIFECTA", "DAILYDOUBLE": "DOUBLE", "SUPERHI5": "SUPERHIGHFIVE", "SUPERHIGHFIVE": "SUPERHIGHFIVE",
            "HI5": "SUPERHIGHFIVE", "PENTAFECTA": "SUPERHIGHFIVE"}.get(s, s)


def parse_payout_rows(rows, race_no: int, roster: dict | None = None) -> dict:
    """rows as ocr_rows() returns them; roster = {pgm: horse name} for the race (optional cross-check)."""
    warnings, confs = [], []
    # column positions from the header row
    win_x = place_x = show_x = None
    header_y = pool_y = order_y = None
    condition = surface = official = None
    for y, toks in rows:
        texts = {t.upper(): x for x, t, c in toks}
        line = " ".join(t for x, t, c in toks)
        if "WIN" in texts and ("PLACE" in texts or "SHOW" in texts):
            win_x, place_x, show_x, header_y = texts.get("WIN"), texts.get("PLACE"), texts.get("SHOW"), y
        if any(t.upper().startswith("POOL TYPE") for x, t, c in toks):
            pool_y = y
        if order_y is None and any(t.upper().replace(" ", "") == "FINISHORDER" for x, t, c in toks) and header_y is not None and y > header_y:
            order_y = y
        mc = COND_RE.search(line)
        if mc and header_y is None:
            surface, condition = mc.group(1).upper().replace(" ", ""), mc.group(2).strip().upper()
        if "OFFICIAL" in texts and header_y is None:
            official = True
    if header_y is None:
        warnings.append("no WIN/PLACE/SHOW header found")
    cols = [(k, x) for k, x in (("win", win_x), ("place", place_x), ("show", show_x)) if x is not None]

    def column(x):
        if not cols:
            return None
        return min(cols, key=lambda kx: abs(kx[1] - x))[0]

    # runner blocks between the header and the pool table: name row / jockey row with the amounts and the
    # post-position box ("PP n" is the post, not the program) / trainer row
    runners = []           # {"name", "post", "win", "place", "show"}
    last_text = None       # the most recent text row (candidate horse name)
    skip_trainer = False
    for y, toks in rows:
        if header_y is not None and y <= header_y:
            continue
        if pool_y is not None and y >= pool_y:
            break
        if order_y is not None and y >= order_y:
            break
        amounts = [(x, _money(t), c) for x, t, c in toks if _money(t) is not None and "$" in t]
        post = next((m.group(1).upper() for x, t, c in toks if (m := PP_RE.match(t.replace(" ", "")))), None)
        words = [(x, t, c) for x, t, c in toks if _money(t) is None and not PP_RE.match(t.replace(" ", ""))
                 and not NOISE.match(t.strip()) and x < (win_x or 600) - 60]
        if amounts:
            r = {"name": last_text[1] if last_text and y - last_text[0] <= 40 else None, "post": post, "win": None, "place": None, "show": None}
            for x, v, c in amounts:
                col = column(x)
                if col:
                    r[col] = v
                    confs.append(c)
            runners.append(r)
            last_text, skip_trainer = None, True
        elif words:
            if skip_trainer:
                skip_trainer = False        # the trainer line under the amounts row
                continue
            last_text = (y, words[0][1])
            confs.append(words[0][2])
    # full finish order section (the later "official" page lists every runner): name / jockey+PP / trainer blocks
    full_names = []
    if order_y is not None:
        last_text, skip_trainer, seen_pp = None, False, False
        for y, toks in rows:
            if y <= order_y:
                continue
            post = next((m.group(1).upper() for x, t, c in toks if (m := PP_RE.match(t.replace(" ", "")))), None)
            words = [(x, t, c) for x, t, c in toks if _money(t) is None and not PP_RE.match(t.replace(" ", ""))
                     and not NOISE.match(t.strip()) and x < 600]
            if post is not None or (words and last_text is not None and skip_trainer is False and full_names and y - last_text[0] <= 18):
                # jockey row (carries the PP box) -> the row above was the horse name
                if last_text and (not full_names or full_names[-1][0] != last_text[0]):
                    full_names.append((last_text[0], last_text[1]))
                skip_trainer, last_text = True, None
                continue
            if words:
                if skip_trainer:
                    skip_trainer = False
                    continue
                last_text = (y, words[0][1])
    # exotic pools
    exotics, seen = [], set()
    if pool_y is not None:
        prev = None
        for y, toks in rows:
            if y <= pool_y:
                continue
            if order_y is not None and y >= order_y:
                break
            first = toks[0][1] if toks else ""
            mp = POOL_RE.match(first.strip())
            if mp:
                combo = next((t.replace(" ", "") for x, t, c in toks[1:] if COMBO_RE.match(t.replace(" ", "")) or ("/" in t and re.search(r"\d", t))), None)
                paid = next((_money(t) for x, t, c in reversed(toks) if "$" in t and _money(t) is not None), None)
                e = {"type": _norm_pool(mp.group("pool"), mp.group("n")), "base": float(mp.group("base")), "combo": combo, "payout": paid}
                confs.extend(c for x, t, c in toks)
                prev = e
                if combo is None or paid is None:
                    warnings.append(f"{e['type']}: could not read combo/payout ({first})")
                    continue
                if e["type"] in seen:        # a second line for the same pool is a consolation ("5 of 6")
                    continue
                seen.add(e["type"])
                exotics.append(e)
            elif prev and CONSOL_RE.search(" ".join(t for x, t, c in toks)):
                if prev in exotics and len([x for x in exotics if x["type"] == prev["type"]]) == 1 and prev.get("consolation_checked") is None:
                    # a consolation marker directly under a pool line: keep the line only if it is the first of its type
                    prev["consolation_checked"] = True
    for e in exotics:
        e.pop("consolation_checked", None)
    # finish order from the combinations
    finish = []
    for key in ("SUPERHIGHFIVE", "SUPERFECTA", "TRIFECTA", "EXACTA", "QUINELLA"):
        e = next((x for x in exotics if x["type"] == key and x.get("combo")), None)
        if e:
            parts = [p for p in re.split(r"[/]", e["combo"]) if p]
            if key == "QUINELLA" and len(parts) == 2:
                continue   # unordered; only useful if nothing else
            cand = [p.split(",")[0] for p in parts]
            if len(cand) > len(finish):
                finish = cand
    # runner-derived order: win -> place -> show
    order = sorted(runners, key=lambda r: (r["win"] is None, r["place"] is None, r["show"] is None))
    names = [r["name"] for r in order]
    posts = [r["post"] for r in order]
    # cross-check against the roster names
    name_pgms = []
    if roster:
        inv = {v.lower(): k for k, v in roster.items()}
        for nm in names:
            if not nm:
                name_pgms.append(None)
                continue
            best = difflib.get_close_matches(nm.lower(), list(inv.keys()), n=1, cutoff=0.6)
            name_pgms.append(inv[best[0]] if best else None)
        for i, (pg, nm) in enumerate(zip(name_pgms[:3], names[:3])):
            if pg is None:
                warnings.append(f"runner '{nm}' not matched to the card")
            elif i < len(finish) and str(pg) != str(finish[i]):
                warnings.append(f"{['1st', '2nd', '3rd'][i]}: combos say #{finish[i]} but the name '{nm}' is #{pg}")
    if not finish and roster and name_pgms and all(name_pgms[:3]):
        finish = [str(p) for p in name_pgms[:3]]
        warnings.append("finish order taken from the runner names (no exotic combination read)")
    elif not finish:
        warnings.append("no finish order: no exotic combination read and no roster to match names")
    # extend the finish with the full-order section when the roster can name every runner
    full_pgms = []
    if full_names and roster:
        inv = {v.lower(): k for k, v in roster.items()}
        for _, nm in full_names:
            best = difflib.get_close_matches(nm.lower(), list(inv.keys()), n=1, cutoff=0.6)
            full_pgms.append(inv[best[0]] if best else None)
        if full_pgms and all(full_pgms) and len(set(full_pgms)) == len(full_pgms):
            if full_pgms[:len(finish)] == [str(x) for x in finish]:
                finish = [str(x) for x in full_pgms]
            else:
                warnings.append(f"finish-order section ({'/'.join(full_pgms)}) disagrees with the combinations ({'/'.join(finish)})")
        else:
            warnings.append("finish-order section: not every runner matched to the card; top finishers from the combinations only")
    race = {"race_no": race_no, "finish": finish, "exotics": [{k: v for k, v in e.items()} for e in exotics]}
    if condition:
        race["track_condition"] = condition
        race["surface"] = surface
    if official:
        race["official"] = True
    by_pos = {}
    for i, r in enumerate(order[:3]):
        pg = finish[i] if i < len(finish) else None
        if pg:
            by_pos[pg] = r
    if order and order[0]["win"] is not None:
        race["win"] = order[0]["win"]
    place = {pg: r["place"] for pg, r in by_pos.items() if r["place"] is not None}
    show = {pg: r["show"] for pg, r in by_pos.items() if r["show"] is not None}
    if place:
        race["place"] = place
    if show:
        race["show"] = show
    if len(runners) < 3:
        warnings.append(f"only {len(runners)} runner rows read")
    race["ocr"] = {"names": names, "posts": posts, "name_pgms": name_pgms, "full_order_names": [n for _, n in full_names],
                   "confidence": round(min(confs), 2) if confs else None, "warnings": warnings}
    return race


def read_screenshot(path: str, race_no: int, roster: dict | None = None) -> dict:
    return parse_payout_rows(ocr_rows(path), race_no, roster)
