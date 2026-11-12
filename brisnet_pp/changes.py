"""
Equibase "Today's Race Day Changes" page reader (the per-track late-changes page, saved from the browser as
HTML).  Pure data capture: it fills the scratch list the way you would type it and records what the engine does
not read anywhere else - the morning track condition, the scheduled first post, temporary rail settings, jockey
changes, equipment / gelding notes and pools the track is not offering.  Nothing here changes a score.

parse_changes(html) -> {
    "track": "Churchill Downs", "updated": "November 11, 11:51 AM ET", "first_post": "1:00 PM ET",
    "conditions": {"dirt": "Fast", "turf": "Firm"},
    "races": {5: {"notes": ["Temp Rail Distance set at 24 ft."], "rail": 24.0, "pools_not_offered": [],
                  "horses": [{"pgm": "8", "name": "Mo Way", "changes": [{"text": "Scratched - Trainer", "time": "10:20 AM ET"}]}, ...]}}
}
scratch_spec(changes) -> "1:1, 1:3, 4:5, ..."   every horse whose latest change says Scratched (an also-eligible
                                                scratched off the list included: it cannot draw in)
"""
from __future__ import annotations

import html as _html
import re

SCRATCH_RE = re.compile(r"^\s*Scratched\b", re.I)
JOCKEY_RE = re.compile(r"^\s*Jockey\s*-\s*(.+?)\s+changed to\s+(.+?)\s*$", re.I)
RAIL_RE = re.compile(r"Rail\s+Distance\s+set\s+at\s+(\d+(?:\.\d+)?)\s*ft", re.I)
NO_POOL_RE = re.compile(r"^\s*No\s+(.+?)\s+Wagering\s*$", re.I)


def _text(fragment: str) -> list[str]:
    """Visible lines of an HTML fragment (<br> = line break), entities decoded, whitespace squeezed."""
    t = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
    t = _html.unescape(re.sub(r"<[^>]+>", "", t))
    return [re.sub(r"\s+", " ", x).strip() for x in t.split("\n") if re.sub(r"\s+", " ", x).strip()]


def parse_changes(page: str) -> dict:
    out = {"track": None, "updated": None, "first_post": None, "conditions": {}, "races": {}}
    m = re.search(r"(.{0,600})Last Updated:", page, re.S)
    if m:   # the track name is the last visible line before "Last Updated"
        lines = [l for l in _text(re.sub(r"(?is)<(script|style).*?</\1>", " ", m.group(1))) if "{" not in l and "(" not in l]
        out["track"] = lines[-1] if lines else None
    m = re.search(r"Last Updated:\s*([^<]+)", page)
    if m:
        out["updated"] = m.group(1).strip()
    for surf in ("Dirt", "Turf", "Inner Turf", "Outer Turf", "All Weather", "Synthetic"):
        m = re.search(r"<b>\s*%s:\s*</b>\s*([^<]+)" % re.escape(surf), page)
        if m:
            out["conditions"][surf.lower().replace(" ", "_")] = m.group(1).strip()
    m = re.search(r"Scheduled First Post:\s*</b>\s*([^<]+)", page)
    if m:
        out["first_post"] = m.group(1).strip()
    tbl = re.search(r'<table[^>]*id="fullChanges".*?</table>', page, re.S)
    if not tbl:
        return out
    race = None
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl.group(0), re.S):
        hdr = re.search(r'class="race"[^>]*>\s*Race:\s*(\d+)', row)
        if hdr:
            race = out["races"].setdefault(int(hdr.group(1)), {"notes": [], "rail": None, "pools_not_offered": [], "horses": []})
            continue
        if race is None:
            continue
        cells = {m.group(1): m.group(2) for m in re.finditer(r'<td[^>]*class="(pgm|horse|changes|time)"[^>]*>(.*?)</td>', row, re.S)}
        times = _text(cells.get("time", ""))
        if "pgm" not in cells and "changes" in cells and race["horses"]:
            # continuation row for the horse above ("Scratch Reason - ... changed to Also-Eligible")
            for i, c in enumerate(_text(cells["changes"])):
                race["horses"][-1]["changes"].append({"text": c, "time": times[i] if i < len(times) else None})
            continue
        if "pgm" not in cells:   # race-level line: "No Superfecta ... Wagering", "Temp Rail Distance set at 24 ft."
            tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            for line in (_text(tds[0]) if tds else []):
                race["notes"].append(line)
                r = RAIL_RE.search(line)
                if r:
                    race["rail"] = float(r.group(1))
                n = NO_POOL_RE.match(line)
                if n:
                    race["pools_not_offered"] += [p.strip() for p in re.split(r",|\bor\b", n.group(1)) if p.strip()]
            continue
        pgm = (_text(cells.get("pgm", "")) or [""])[0].lstrip("#").strip()
        name = (_text(cells.get("horse", "")) or [""])[0]
        changes = _text(cells.get("changes", ""))
        entry = {"pgm": pgm, "name": name,
                 "changes": [{"text": c, "time": times[i] if i < len(times) else None} for i, c in enumerate(changes)]}
        race["horses"].append(entry)
    return out


def scratch_spec(changes: dict) -> str:
    """The scratch list as the engine takes it: every horse whose changes say Scratched."""
    toks = []
    for rn in sorted(changes.get("races", {})):
        for h in changes["races"][rn]["horses"]:
            if any(SCRATCH_RE.match(c["text"]) for c in h["changes"]) and h["pgm"]:
                toks.append(f"{rn}:{h['pgm'].upper()}")
    return ", ".join(toks)


def summary(changes: dict) -> dict:
    """What goes into the run block: conditions, first post, per-race rail / jockey changes / notes / pools."""
    races = {}
    for rn, r in changes.get("races", {}).items():
        jockeys = []
        other = []
        for h in r["horses"]:
            for c in h["changes"]:
                m = JOCKEY_RE.match(c["text"])
                if m:
                    jockeys.append({"pgm": h["pgm"], "name": h["name"], "from": m.group(1), "to": m.group(2)})
                elif not SCRATCH_RE.match(c["text"]) and not c["text"].lower().startswith("scratch reason"):
                    other.append({"pgm": h["pgm"], "name": h["name"], "text": c["text"]})
        races[str(rn)] = {"rail": r["rail"], "pools_not_offered": r["pools_not_offered"], "notes": r["notes"],
                          "jockey_changes": jockeys, "horse_notes": other}
    return {"track": changes.get("track"), "updated": changes.get("updated"), "first_post": changes.get("first_post"),
            "conditions": changes.get("conditions", {}), "races": races}


def merge_scratch_specs(*specs: str | None) -> str:
    """Union of scratch lists, keeping +/- tokens, ordered by race then program."""
    from handicapper.results import parse_scratch_spec
    merged: dict[int, list[str]] = {}
    for spec in specs:
        for rn, toks in parse_scratch_spec(spec or "").items():
            for t in toks:
                if t not in merged.setdefault(rn, []):
                    merged[rn].append(t)
    return ", ".join(f"{rn}:{t}" for rn in sorted(merged) for t in merged[rn])
