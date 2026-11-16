"""Plain English for everything the Desk and the reports say about a horse (Phase F, ASD-STE100 style): short
sentences, one idea each, approved words, no unexplained abbreviation.  The rule id stays as a reference in
brackets at the end of a note: "Ran the fastest speed figure in the field last time (S1, +6.0)".

`plain(text)` expands every glossary abbreviation the first time it appears in a string (the abbreviation stays
in brackets so the reference is not lost), rewrites the engine's shorthand, and capitalises the first letter.
Quoted chart comments ('4w turn, weakened') are the chart's words and are left as they are.  `violations(strings)`
is the test: an abbreviation that appears without its expansion in the same string is a violation.
"""
from __future__ import annotations

import re

# abbreviation -> expansion (the abbreviation is kept in brackets after the expansion)
GLOSSARY = {
    "E1": "early pace", "E2": "second-call pace", "LP": "late pace", "ML": "morning line",
    "ITM": "in the money", "AE": "also-eligible", "MTO": "main-track-only", "AWD": "average winning distance",
    "SPI": "sire production index", "DPI": "dam production index", "PP": "Prime Power", "CR": "class rating",
    "SR": "speed rating", "TF": "Timeform", "ROI": "return on investment", "EV": "expected value",
    "DQ": "disqualified", "DNF": "did not finish", "FTS": "first-time starter",
    "BE": "break-even", "RH": "relative humidity", "L60": "last 60 days", "YTD": "year to date",
}
# Brisnet's race-class codes (MSW, MCL, OC, ALW, CLM, STK) are printed as the PP prints them: they name the race, not the horse
RACE_CLASS_CODES = {"MSW": "maiden special weight", "MCL": "maiden claiming", "OC": "optional claiming", "ALW": "allowance", "CLM": "claiming", "STK": "stakes"}
# shorthand -> words (whole words, case-sensitive; applied outside quoted comments)
SHORTHAND = [
    (r"\bavg\b", "average"), (r"\bvs\.?\b", "against"), (r"\bpts\b", "points"), (r"\bjky/trn\b", "jockey and trainer"),
    (r"\bjky\b", "jockey"), (r"\btrn\b", "trainer"), (r"\bfigs\b", "speed figures"), (r"\bfig\b", "speed figure"),
    (r"\bwks\b", "works"), (r"\bwk\b", "work"), (r"\bmdn\b", "maiden"), (r"\bclm\b", "claiming"), (r"\balw\b", "allowance"),
    (r"\bsprint→route\b", "sprint to route"), (r"\broute→sprint\b", "route to sprint"), (r"(\d(?:\.\d+)?)L\b", r"\1 lengths"),
    (r"\b(\d+)yo\b", r"\1-year-old"), (r"\bhigh-pts\b", "high speed points"), (r"\blast-3\b", "last three"), (r"\bbest-of-last-3\b", "best of the last three"),
    (r"\bpar-(\d+)\b", r"par minus \1"), (r"\bpar\+(\d+)\b", r"par plus \1"), (r"\b1st\b", "first"), (r"\b2nd\b", "second"), (r"\b3rd\b", "third"),
    (r"\bE types\b", "early types"), (r"\bE/P\b", "early-presser"), (r"\bno\.\s", "number "),
]
PHRASES = [
    (r"^ELIMINATED: ", "Eliminated: "), (r"^FLAG: ", "Flag: "),
    (r"^top last-race (speed figure|fig) (\d+)", r"Ran the fastest speed figure in the field last time (\2)"),
    (r"^last speed (\d+) is top in field", r"Last speed figure \1 is the best in the field"),
    (r"^best recent (\d+) beats field best (\d+) by (\d+)", r"Best recent speed figure \1 beats the field's best \2 by \3"),
    (r"^figures falling", "Speed figures are falling"), (r"^paired figures", "Two matching speed figures"),
    (r"^beaten ([\d.]+) lengths but ran (\d+) against par (\d+)", r"Beaten \1 lengths but ran a \2 against a par of \3"),
    (r"^trouble: ", "Had trouble last time: "), (r"^bullet work", "Fastest work of the day (bullet work)"),
    (r"^switches to (\d+)% rider", r"Switches to a jockey who wins \1% of starts"), (r"^trainer (\d+)%$", r"Trainer wins \1% of starts"),
    (r"^dueled and finished ([\d.]+) lengths back", r"Fought for the lead and finished \1 lengths back"),
    (r"^hot pace \(", "Hot pace expected ("), (r"^stretches out:", "Stretches out to a longer distance:"), (r"^cuts back with", "Cuts back to a shorter distance with"),
    (r"^overlay: ", "Overlay (the price is longer than the engine's fair odds): "), (r"^underlay: ", "Underlay (the price is shorter than the engine's fair odds): "),
    (r"^no factor", "No factor"),
]
_QUOTE = re.compile(r"'[^']*'|\"[^\"]*\"")


def _outside_quotes(text: str, fn) -> str:
    out, last = [], 0
    for m in _QUOTE.finditer(text):
        out.append(fn(text[last:m.start()])); out.append(m.group(0)); last = m.end()
    out.append(fn(text[last:]))
    return "".join(out)


def expand(text: str) -> str:
    """Every glossary abbreviation, first occurrence per string, becomes 'expansion (ABBR)'; later ones stay."""
    seen = set()

    def one(seg: str) -> str:
        def rep(m):
            a = m.group(0)
            if a in seen:
                return a
            seen.add(a)
            return f"{GLOSSARY[a]} ({a})"
        return re.sub(r"(?<![\w(/-])(" + "|".join(sorted(GLOSSARY, key=len, reverse=True)) + r")(?![\w)/-])", rep, seg)
    # an abbreviation already followed by its own bracket, or inside brackets after its expansion, counts as seen
    for a, x in GLOSSARY.items():
        if re.search(re.escape(x) + r"\s*\(" + re.escape(a) + r"\)", text, re.I):
            seen.add(a)
    return _outside_quotes(text, one)


def plain(text: str | None) -> str | None:
    """Plain-English rendering of one horse-facing string.  Idempotent."""
    if text is None or not isinstance(text, str) or not text.strip():
        return text
    t = _outside_quotes(text, lambda seg: _shorthand(seg))     # shorthand first, so the phrase patterns see words
    for pat, rep in PHRASES:
        t = re.sub(pat, rep, t)
    t = expand(t)
    if t and t[0].islower():
        t = t[0].upper() + t[1:]
    return t


def _shorthand(seg: str) -> str:
    for pat, rep in SHORTHAND:
        seg = re.sub(pat, rep, seg)
    return seg


def violations(strings) -> list[str]:
    """Horse-facing strings that use a glossary abbreviation without its expansion (outside quoted comments)."""
    bad = []
    pat = re.compile(r"(?<![\w(/-])(" + "|".join(sorted(GLOSSARY, key=len, reverse=True)) + r")(?![\w)/-])")
    for s in strings:
        if not isinstance(s, str):
            continue
        body = _QUOTE.sub("", s)
        for m in pat.finditer(body):
            a = m.group(1)
            if GLOSSARY[a].lower() not in body.lower():
                bad.append(f"{a!r} without {GLOSSARY[a]!r}: {s}")
                break
    return bad


def glossary_markdown() -> str:
    L = ["# Glossary", "", "Every abbreviation the Desk and the reports may show about a horse, and the words it stands for. The first",
         "time one appears on a screen it is written out with the abbreviation in brackets; a horse-facing string that uses one",
         "without its expansion fails `tests/test_plain.py`. Rule ids (S1, P3, X2 ...) are references, kept in brackets at the end of a note.", "",
         "| Abbreviation | Means |", "|---|---|"]
    for a, x in sorted(GLOSSARY.items()):
        L.append(f"| {a} | {x} |")
    L += ["", "## Shorthand the engine used to print, and what it says now", "", "| Was | Now |", "|---|---|"]
    for pat, rep in SHORTHAND:
        L.append(f"| `{pat}` | {rep} |")
    L += ["", "## Race-class codes, printed as Brisnet prints them (they name the race, not the horse)", "", "| Code | Means |", "|---|---|"]
    for a, x in sorted(RACE_CLASS_CODES.items()):
        L.append(f"| {a} | {x} |")
    L += ["", "Chart comments in quotes ('4w turn, weakened') are the chart caller's words and are shown as printed."]
    return "\n".join(L)
