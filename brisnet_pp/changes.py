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


# ---------------------------------------------------------------------------
# Equibase late-changes XML: one file for every track racing that day (schema: late_changes.xsd)
# ---------------------------------------------------------------------------
SURFACE_WORDS = ("turf", "dirt", "main track", "tapeta", "all weather", "all-weather", "synthetic", "inner", "outer")


def is_late_changes_xml(text: str | bytes) -> bool:
    head = (text[:2000] if isinstance(text, str) else text[:2000].decode("utf-8", errors="replace")).lstrip()
    return head.startswith("<") and "<late_changes" in head


def iso_date(text: str | None) -> str | None:
    """'11/18/2026', '2026-11-18', '11-18-2026', 'November 18, 2026' -> '2026-11-18'; None when unreadable."""
    if not text:
        return None
    from datetime import datetime
    t = text.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y%m%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%y"):
        try:
            return datetime.strptime(t, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _xml_text(el, tag: str) -> str:
    x = el.find(tag)
    return (x.text or "").strip() if x is not None and x.text else ""


def parse_late_changes_xml(text: str | bytes) -> dict:
    """The day's Equibase late-changes XML -> {"race_date", "tracks": [{"track_name", "id", "country", "changes": <the same
    dict parse_changes() returns for one track>}]}.  Every change is kept verbatim in `raw`; the per-track dict is
    built from it so scratch_spec(), summary() and the pipeline's off-turf / pools-not-offered inputs work unchanged:
      start_changes/horse/change  -> horse changes ("Scratched - <reason>", "Jockey - A changed to B", or "<description>: old -> new")
      race_changes/change         -> race notes; a surface change from turf to a main surface adds an "Off Turf" note;
                                     a condition change fills `conditions`; a rail change fills `rail`
      wager_cancellations/wager   -> pools_not_offered (the wager type) and a "No <type> Wagering" note
    The change descriptions Equibase prints are matched by keyword (scratch, jockey, surface / course, condition, rail,
    post time, equipment); anything else is kept as "<description>: old -> new"."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(text if isinstance(text, (str, bytes)) else str(text))
    if root.tag != "late_changes":
        raise ValueError(f"not an Equibase late_changes document (root element {root.tag!r})")
    raw_date = _xml_text(root, "race_date") or None
    out = {"race_date": iso_date(raw_date) or raw_date, "race_date_text": raw_date, "tracks": []}
    for tr in root.findall("track"):
        chg = {"track": (tr.get("track_name") or "").strip() or None, "track_id": (tr.get("id") or "").strip() or None,
               "country": tr.get("country"), "updated": None, "first_post": None, "conditions": {}, "races": {}, "raw": [],
               "source": "equibase_late_changes_xml", "race_date": out["race_date"]}
        latest = None
        for race in tr.findall("race"):
            try:
                rn = int(race.get("race_number"))
            except (TypeError, ValueError):
                continue
            r = chg["races"].setdefault(rn, {"notes": [], "rail": None, "pools_not_offered": [], "horses": []})
            rc = race.find("race_changes")
            for c in (rc.findall("change") if rc is not None else []):
                d, old, new, when = _xml_text(c, "change_description"), _xml_text(c, "old_value"), _xml_text(c, "new_value"), _xml_text(c, "date_changed")
                chg["raw"].append({"race": rn, "scope": "race", "description": d, "old": old, "new": new, "when": when})
                latest = max(latest or "", when)
                low = d.lower()
                r["notes"].append(f"{d}: {old} -> {new}" if old or new else d)
                if "rail" in low:
                    m = re.search(r"(\d+(?:\.\d+)?)", new)
                    r["rail"] = float(m.group(1)) if m else r["rail"]
                if any(w in low for w in ("surface", "course")) and "condition" not in low:
                    if "turf" in old.lower() and new and "turf" not in new.lower():
                        r["notes"].append(f"Off Turf: race moved from {old} to {new}")
                elif "condition" in low:
                    key = "turf" if "turf" in low or "turf" in old.lower() or "course" in low else "dirt"
                    chg["conditions"][key] = new or chg["conditions"].get(key)
                if "post" in low and "time" in low and rn == min(chg["races"]):
                    chg["first_post"] = new or chg["first_post"]
            sc = race.find("start_changes")
            for h in (sc.findall("horse") if sc is not None else []):
                entry = {"pgm": (h.get("program_number") or "").strip(), "name": (h.get("horse_name") or "").strip(), "changes": []}
                for c in h.findall("change"):
                    d, old, new, when = _xml_text(c, "change_description"), _xml_text(c, "old_value"), _xml_text(c, "new_value"), _xml_text(c, "date_changed")
                    chg["raw"].append({"race": rn, "scope": "horse", "pgm": entry["pgm"], "name": entry["name"], "description": d, "old": old, "new": new, "when": when})
                    latest = max(latest or "", when)
                    low = d.lower()
                    if "scratch" in low and "reason" not in low:
                        text_ = "Scratched" + (f" - {new}" if new and new.lower() not in ("scratched", "yes", "true") else (f" - {old}" if old and "scratch" not in old.lower() else ""))
                    elif "scratch" in low and "reason" in low:
                        text_ = f"Scratch Reason - {old} changed to {new}" if old else f"Scratch Reason - {new}"
                    elif "jockey" in low or "rider" in low:
                        text_ = f"Jockey - {old} changed to {new}"
                    else:
                        text_ = f"{d} - {old} changed to {new}" if old else (f"{d} - {new}" if new else d)
                    entry["changes"].append({"text": text_, "time": when or None})
                r["horses"].append(entry)
            wc = race.find("wager_cancellations")
            for w in (wc.findall("wager") if wc is not None else []):
                t = (w.get("type") or "").strip()
                old, new, when = _xml_text(w, "old_value"), _xml_text(w, "new_value"), _xml_text(w, "date_changed")
                chg["raw"].append({"race": rn, "scope": "wager", "type": t, "old": old, "new": new, "when": when})
                latest = max(latest or "", when)
                if t and t not in r["pools_not_offered"]:
                    r["pools_not_offered"].append(t)
                r["notes"].append(f"No {t} Wagering" + (f" ({new})" if new else ""))
        chg["updated"] = latest
        out["tracks"].append({"track_name": chg["track"], "id": chg["track_id"], "country": chg["country"], "changes": chg})
    return out


def changes_for_track(doc: dict, track_code: str | None = None, track_name: str | None = None, cfg: dict | None = None) -> dict | None:
    """The one track's changes out of the day's XML, matched by Equibase id (track code) or by name."""
    from handicapper.identity import canonical_track, norm_name
    code = (track_code or "").upper()
    want = norm_name(track_name)
    for t in doc.get("tracks", []):
        tid = (t.get("id") or "").upper()
        if code and tid and tid == code:
            return t["changes"]
    for t in doc.get("tracks", []):
        tc = canonical_track(t.get("track_name"), cfg) or canonical_track(t.get("id"), cfg)
        if code and tc and tc == code:
            return t["changes"]
        if want and norm_name(t.get("track_name")) == want:
            return t["changes"]
    return None


def load_changes_file(path: str, track_code: str | None = None, track_name: str | None = None, cfg: dict | None = None) -> dict | None:
    """A saved changes page (HTML, one track) or the day's late-changes XML (every track): the dict for one track."""
    with open(path, "rb") as fh:
        data = fh.read()
    if is_late_changes_xml(data):
        return changes_for_track(parse_late_changes_xml(data), track_code, track_name, cfg)
    return parse_changes(data.decode("utf-8", errors="replace"))
