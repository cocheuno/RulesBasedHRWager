"""
Decoding of the Brisnet "PP2B" symbol font used in Ultimate PPs PDFs.

Every mapping here was verified empirically against the Del Mar 2026-11-06
card (e.g. jockey weight "FreyK¨¨¯" == 118, race-number superscripts,
"1ˆ" == 1 1/16 miles, "1„" == 1 1/8 miles, "1‰" == 1 3/16 miles).
"""
from __future__ import annotations

import re

# Superscript digits (used for race numbers, lengths, weights, race/class ratings)
SUP_DIGITS = {
    "§": "0",  # §
    "¨": "1",  # ¨
    "©": "2",  # ©
    "ª": "3",  # ª
    "«": "4",  # «
    "¬": "5",  # ¬
    "­": "6",  # soft hyphen glyph
    "®": "7",  # ®
    "¯": "8",  # ¯
    "°": "9",  # °
}
SUP_CLASS = "[" + "".join(re.escape(k) for k in SUP_DIGITS) + "]"

# Fractional lengths & margin words
FRACTIONS = {
    "\u0081": 0.25,   # ¼
    "‚": 0.5,    # ½  (‚)
    "ƒ": 0.75,   # ¾  (ƒ)
}
MARGIN_WORDS = {
    "±": ("nk", 0.3),   # ± neck
    "²": ("hd", 0.2),   # ² head
    "³": ("no", 0.1),   # ³ nose
    "´": ("dh", 0.0),   # ´ dead heat (rare)
}
FRAC_CLASS = "[" + "".join(re.escape(k) for k in FRACTIONS) + "]"
MARGIN_CLASS = "[" + "".join(re.escape(k) for k in MARGIN_WORDS) + "]"

# Distance fraction glyphs that follow a mile count ("1ˆ" = 1 1/16 mi)
DIST_FRACTIONS = {
    "ˆ": 1 / 16,   # ˆ  1/16
    "„": 1 / 8,    # „  1/8
    "‰": 3 / 16,   # ‰  3/16
    "‚": 1 / 2,    # ‚  1/2   ("1‚" = 1 1/2 mi, seen on Epsom)
    "½": 1 / 2,    # ½ (real glyph, used for 5½f / 6½f)
}

# Race-type prefix / misc symbols
SYM_FILLIES = "™"       # ™  fillies / fillies & mares race
SYM_STATEBRED = "‘"     # ‘  state-bred restricted
SYM_CLAIM_C = "’"       # ’  seen on "Moc62500-N" lines (optional-claiming marker)
SYM_TURF = "à"          # à  turf course
SYM_AW = "Ì"            # Ì  all-weather / synthetic
SYM_AGE_3UP = "¦"       # ¦  race was for 3 & up
SYM_AGE_4UP = "¡"       # ¡  race was for 4 & up
SYM_POS = "ñ"           # ñ  positive QuickPlay comment bullet
SYM_NEG = "×"           # ×  negative QuickPlay comment bullet
SYM_FIRST_LASIX = "È"   # È  first-time Lasix
SYM_NAME_FLAG = "ì"     # ì  flag printed after run style (kept raw)
SYM_WORK_TURF = "˜"     # ˜  workout on turf course marker (followed by "(d)")

TRACK_CONDITIONS = {"ft", "gd", "my", "sy", "wf", "fm", "yl", "sf", "hy", "sl", "fr", "sys", "sl"}


def sup_to_int(s: str) -> int | None:
    """'¨¨¯' -> 118.  Returns None if s contains no superscript digits."""
    digits = "".join(SUP_DIGITS.get(ch, "") for ch in s)
    return int(digits) if digits else None


def decode_sup(s: str) -> str:
    """Replace superscript digit glyphs with normal digits (fractions untouched)."""
    return "".join(SUP_DIGITS.get(ch, ch) for ch in s)


_POS_RE = re.compile(
    r"^\s*(?P<pos>\d{1,2})?\s*(?P<len>" + SUP_CLASS + r"*)(?P<frac>" + FRAC_CLASS + r")?(?P<marg>" + MARGIN_CLASS + r")?\s*$"
)


def parse_call(s: str) -> dict:
    """
    Parse a running-line call like '7­ƒ' -> position 7, 6.75 lengths behind.
    '1²' -> position 1, margin 'hd' (ahead by a head when position == 1).
    Returns {'pos': int|None, 'lengths': float|None, 'margin': str|None, 'raw': s}
    """
    s = s.strip()
    out = {"pos": None, "lengths": None, "margin": None, "raw": s}
    if not s or s == "-":
        return out
    m = _POS_RE.match(s)
    if not m:
        return out
    if m.group("pos"):
        out["pos"] = int(m.group("pos"))
    lengths = 0.0
    have = False
    if m.group("len"):
        lengths += int(decode_sup(m.group("len")))
        have = True
    if m.group("frac"):
        lengths += FRACTIONS[m.group("frac")]
        have = True
    if m.group("marg"):
        word, val = MARGIN_WORDS[m.group("marg")]
        out["margin"] = word
        lengths += val
        have = True
    out["lengths"] = round(lengths, 2) if have else (0.0 if out["pos"] is not None else None)
    return out


def parse_time(s: str) -> float | None:
    """':23«' -> 23.8 ; '1:43ª' -> 103.6 ; '2:15«' -> 135.8"""
    s = s.strip()
    if not s:
        return None
    m = re.match(r"^(?:(\d*):)?(\d\d)(" + SUP_CLASS + r")?$", s)
    if not m:
        return None
    mins = int(m.group(1)) if m.group(1) else 0
    secs = int(m.group(2))
    tenths = int(SUP_DIGITS[m.group(3)]) if m.group(3) else 0
    return mins * 60 + secs + tenths / 10.0


def parse_distance(s: str) -> tuple[float | None, str]:
    """
    Distance text (symbol-font) -> (furlongs, normalized text).
    '6f' -> 6.0 ; '5½' -> 5.5 ; '1m' -> 8.0 ; '1ˆ' -> 8.5 ; '1„' -> 9.0 ; '1‰' -> 9.5 ; '1‚' -> 12.0
    """
    s = s.strip()
    m = re.match(r"^(\d+)(?:(f)|(m)|([ˆ„‰‚½]))?$", s)
    if not m:
        return None, s
    n = int(m.group(1))
    if m.group(2):
        return float(n), f"{n}f"
    if m.group(3):
        return 8.0 * n, f"{n}m"
    if m.group(4):
        frac = DIST_FRACTIONS[m.group(4)]
        if n >= 1 and frac in (1 / 16, 1 / 8, 3 / 16, 1 / 2) and m.group(4) != "½":
            # miles + fraction of a mile
            miles = n + frac
            return round(miles * 8.0, 2), f"{n}{frac_label(frac)}m"
        # furlongs + ½
        return n + 0.5, f"{n}½f"
    return None, s


def frac_label(frac: float) -> str:
    return {1 / 16: " 1/16", 1 / 8: " 1/8", 3 / 16: " 3/16", 1 / 2: " 1/2"}.get(frac, "")


def clean_name(s: str) -> str:
    """Strip symbol glyphs from a horse name string."""
    return re.sub(r"[\u0080-ÿ‘’‚„‰™ƒˆ˜]", "", s).strip()
