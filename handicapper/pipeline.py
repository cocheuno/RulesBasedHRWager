"""
One run of the engine on one card: parse (or load), merge the quick sheet, apply scratches, attach earlier
results, choose the track profile, score.  pick.py and the local web app (ui/server.py) both call run_card()
so the command line and the screen can never disagree.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone

from brisnet_pp.parser import parse_pdf
from brisnet_pp.sheet import merge_sheet, parse_sheet
from .engine import load_config, resolve_track_code, score_card
from .results import apply_scratches, attach_day_bias, load_results, parse_scratch_spec
from .timing import parse_utc, race_cutoffs, timing_summary

OFF_TURF_RE = re.compile(r"off\s+(?:the\s+)?turf|turf\s+(?:race\s+)?(?:moved|transferred|switched)\s+to|(?:moved|transferred|switched)\s+to\s+(?:the\s+)?(?:main|dirt|tapeta|all[- ]?weather|synthetic)", re.I)
TURF_ON_RE = re.compile(r"(?:remains?|stays?|will\s+be\s+run)\s+on\s+(?:the\s+)?turf", re.I)


def race_inputs(race: dict, chg_sum: dict | None) -> dict:
    """What the Equibase changes page says about one race, as inputs a rule may read (after the freeze): morning
    condition for the race's surface, whether the race came off the turf, the pools the track will not sell, the rail."""
    rs = (chg_sum or {}).get("races", {}).get(str(race["race_no"])) or {}
    conds = (chg_sum or {}).get("conditions") or {}
    texts = list(rs.get("notes") or []) + [x.get("text", "") for x in rs.get("horse_notes") or []]
    off_turf = any(OFF_TURF_RE.search(t) and not TURF_ON_RE.search(t) for t in texts)
    surf = race.get("surface")
    cond_key = "turf" if surf == "turf" else "dirt"
    return {"source": "equibase_changes" if chg_sum else None, "updated": (chg_sum or {}).get("updated"),
            "track_condition_morning": conds.get(cond_key) if chg_sum else None, "conditions": conds if chg_sum else None,
            "off_turf": off_turf, "pools_not_offered": list(rs.get("pools_not_offered") or []), "rail": rs.get("rail"),
            "notes": list(rs.get("notes") or [])}


def apply_surface_switch(race: dict, to_surface: str, notes: list[str]) -> None:
    """A turf race taken off the turf runs on the track's main surface: record the switch, score on the new surface
    and activate the main-track-only entrants (they run only in this case)."""
    if race.get("surface") != "turf" or race.get("surface_switch"):
        return
    race["surface_switch"] = {"from": "turf", "to": to_surface, "source": "equibase_changes"}
    race["surface"] = to_surface
    race["track_condition_morning"] = ((race.get("inputs") or {}).get("conditions") or {}).get("dirt")
    if race.get("inputs"):
        race["inputs"]["track_condition_morning"] = race["track_condition_morning"]   # the condition of the surface it now runs on
    on = []
    for h in race["horses"]:
        if (h.get("entry_status") or "").upper() == "MTO":
            h["entry_status"] = None
            on.append(f"#{h['pgm']} {h['name']}")
    notes.append(f"R{race['race_no']}: off the turf, scored as {to_surface}" + (f"; MTO in: {', '.join(on)}" if on else ""))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(ROOT, "rules_config.json")


def _sha256(path: str | None) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, TypeError):
        return None


def code_version() -> str | None:
    """git HEAD of the repository the engine runs from (None outside a checkout or without git)."""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=3)
        return out.stdout.strip() or None
    except Exception:
        return None


def config_hash(cfg: dict) -> str:
    """Fingerprint of the effective configuration (weights, selection, probability, multirace, wagering)."""
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:16]


def load_card(source) -> tuple[dict, list[str]]:
    """A parsed card from a PDF path, a card JSON path, or an already-parsed dict (deep-copied)."""
    notes = []
    if isinstance(source, dict):
        return copy.deepcopy(source), notes
    if str(source).lower().endswith(".json"):
        with open(source, encoding="utf-8") as fh:
            return json.load(fh), notes
    card = parse_pdf(source)
    notes.extend(f"parser warning: {w}" for w in card.get("warnings", []))
    return card, notes


def run_card(source, *, scratch: str | None = None, sheet: str | None = None, results: str | dict | None = None,
             config_path: str = DEFAULT_CONFIG, track_profile: str | None = None, multirace: bool = True,
             budget3: float | None = None, budget4: float | None = None, race_no: int | None = None,
             changes: str | dict | None = None, timeform: str | dict | None = None, weather: str | list | None = None,
             boards: dict | None = None, racing_dudes: str | dict | None = None) -> dict:
    """Returns {"card": the card as scored (after scratches), "raw": the card before scratches, "result": picks,
    "cfg": config used, "track_code", "notes": [...]}.  `changes`: a saved Equibase race-day-changes page (path)
    or its parsed form; recorded on the run (conditions, rail, jockey changes, pools) and on each race as inputs; a
    race the page takes off the turf is scored on the track's main surface (tracks.<code>.off_turf_surface) with its
    MTO entrants in.  `timeform`: a TimeformUS PP PDF (path) or its parsed form, merged under its own namespace.
    `weather`: "auto" fetches the forecast for the track's configured location (optional; "unavailable" on failure),
    or a list of observations (manual / replayed) to record."""
    card, notes = load_card(source)
    base_cfg = load_config(config_path)
    code0 = track_profile or resolve_track_code(card, base_cfg)
    tcfg = (base_cfg.get("tracks", {}).get(code0 or "", {}) or {})
    chg = None
    chg_sum = None
    if changes:
        from brisnet_pp.changes import parse_changes, summary as changes_summary
        chg = changes if isinstance(changes, dict) else parse_changes(open(changes, encoding="utf-8", errors="replace").read())
        chg_sum = changes_summary(chg)
        notes.append(f"changes: {chg_sum.get('track')} updated {chg_sum.get('updated')}; conditions {chg_sum.get('conditions')}"
                     + (f"; first post {chg_sum.get('first_post')}" if chg_sum.get("first_post") else ""))
    for r in card["races"]:
        r["changes"] = chg_sum["races"].get(str(r["race_no"])) if chg_sum else None
        r["inputs"] = race_inputs(r, chg_sum)
        r["track_condition_morning"] = r["inputs"]["track_condition_morning"]
        if r["inputs"]["off_turf"]:
            apply_surface_switch(r, tcfg.get("off_turf_surface", "dirt"), notes)
    tf_doc = None
    if timeform:
        from timeform_pp.reader import merge_timeform, parse_source as parse_timeform
        tf_doc = timeform if isinstance(timeform, dict) else parse_timeform(timeform)
        notes.extend("timeform: " + n for n in merge_timeform(card, tf_doc))
    rd_races = None
    if racing_dudes:
        from racing_dudes.reader import merge_racing_dudes, parse_page as parse_rd, track_day
        if isinstance(racing_dudes, dict) and "tracks" not in racing_dudes:
            rd_races = racing_dudes                                     # already one track and day: {race_no: race}
        else:
            doc = racing_dudes if isinstance(racing_dudes, dict) else parse_rd(open(racing_dudes, "rb").read(), racing_dudes)
            rd_races = track_day(doc, card.get("date"), code0, card.get("track"), base_cfg)
        notes.extend("racing dudes: " + n for n in merge_racing_dudes(card, rd_races, None if isinstance(racing_dudes, dict) else os.path.basename(str(racing_dudes))))
    raw = copy.deepcopy(card)
    if sheet:
        notes.extend("sheet: " + n for n in merge_sheet(card, parse_sheet(sheet)))
    if scratch:
        notes.extend("scratch: " + n for n in apply_scratches(card, parse_scratch_spec(scratch)))
    res = None
    if results:
        res = results if isinstance(results, dict) else load_results(results)
        notes.extend("results: " + n for n in attach_day_bias(card, res))
    if race_no:
        card["races"] = [r for r in card["races"] if r["race_no"] == race_no]
    code = code0
    cfg = load_config(config_path, track_code=code)
    notes.append(f"track: {card.get('track')} ({code or 'unknown code'}); profile: {cfg['track_profile']}")
    if budget3 is not None:
        cfg["multirace"]["pick3"]["budget"] = budget3
    if budget4 is not None:
        cfg["multirace"]["pick4"]["budget"] = budget4
    result = score_card(card, cfg, multirace=multirace)
    from .research import attach as attach_research
    attach_research(result, boards, cfg)      # Phase D: research probabilities, EV diagnostics, NO_BET codes (no pick changes)
    if not result.get("track_code") and code:   # a card parsed before the parser recorded the code
        result["track_code"] = code
    # what this run was made from, so a picks.json on its own says which scratches and parser produced it
    result["scratches"] = scratch or ""
    result["parser_version"] = card.get("parser_version")
    result["run_notes"] = list(notes)
    res_known = sorted(r["race_no"] for r in (res.get("races", []) if results else []) if r.get("finish"))
    result["run"] = {
        "at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scratches": scratch or "", "parser_version": card.get("parser_version"),
        "config_hash": config_hash(cfg), "track_profile": cfg.get("track_profile"), "code_version": code_version(),
        "source": None if isinstance(source, dict) else os.path.basename(str(source)),
        "source_sha256": None if isinstance(source, dict) else _sha256(str(source)),
        "sheet": os.path.basename(sheet) if sheet else None,
        "results_known": res_known,           # races whose results were on file when this run was made
        "odds_source": "morning line",        # the only market input today
        "changes": (chg_sum if chg else None),  # Equibase race-day changes as read (data only; no rule reads it yet)
        "timeform": ({"file": tf_doc.get("file"), "track": tf_doc.get("track"), "date": tf_doc.get("date"), "reader_version": tf_doc.get("reader_version"),
                      "races": len(tf_doc.get("races", []))} if tf_doc else None),
        "surface_switches": {str(r["race_no"]): r["surface_switch"] for r in card["races"] if r.get("surface_switch")},
        "data_sources": [s for s in ("brisnet_pp", "brisnet_power_play" if sheet else None, "equibase_changes" if chg else None,
                                     "timeformus" if tf_doc else None, "racing_dudes" if rd_races else None, "results" if results else None) if s],
    }
    # ---- per-race cutoffs: scheduled post from the PP (Eastern), the chart's off time when a result is on file
    tz = (cfg.get("tracks", {}).get(code or "", {}) or {}).get("timezone")
    by_no = {r["race_no"]: r for r in (res.get("races", []) if res else [])}
    cut = race_cutoffs(card.get("date"), card["races"], parse_utc(result["run"]["at_utc"]), cfg.get("timing", {}).get("cutoff_margin_minutes", 2), by_no, tz)
    result["run"]["cutoffs"] = cut
    result["run"]["timing"] = timing_summary(cut) | {"margin_minutes": cfg.get("timing", {}).get("cutoff_margin_minutes", 2), "track_timezone": tz}
    # ---- weather: a source observation per race (fetched for the post time, or supplied), never read by a rule yet
    from .weather import fetch as fetch_weather, latest_before
    wx = {"status": "not requested", "observations": []}
    supplied = list(weather) if isinstance(weather, list) else list((weather or {}).get("observations") or []) if isinstance(weather, dict) else []
    do_fetch = weather == "auto" or (isinstance(weather, dict) and weather.get("fetch"))
    if do_fetch:
        posts = {rn: c.get("post_at_utc") for rn, c in cut.items() if c.get("post_at_utc")}
        wx = fetch_weather(tcfg.get("location"), posts, tz)
    elif supplied:
        wx = {"status": "supplied"}
    wx["observations"] = [o for o in supplied if o.get("provenance") != "fetched"] + list(wx.get("observations") or []) + \
                         [o for o in supplied if o.get("provenance") == "fetched"]
    result["run"]["weather"] = {k: v for k, v in wx.items() if k != "forecast"}
    for r in result["races"]:
        c = cut.get(str(r["race_no"]), {})
        r["weather"] = latest_before(wx.get("observations") or [], c.get("cutoff_at_utc"), r["race_no"])
    # ---- what each race was scored with: Equibase inputs, surface switch, Timeform side by side (rules read none of it)
    by_race = {r["race_no"]: r for r in card["races"]}
    for r in result["races"]:
        src = by_race.get(r["race_no"], {})
        r["inputs"] = src.get("inputs")
        r["surface_switch"] = src.get("surface_switch")
        r["timeform"] = src.get("timeform")
        r["racing_dudes"] = src.get("racing_dudes")
    # ---- decision records: every suggested wager, frozen with this run (never edited by a later run)
    for r in result["races"]:
        for i, w in enumerate(r.get("wagers", [])):
            key = f"{card.get('track_code')}|{card.get('date')}|{r['race_no']}|{w['type']}|{'/'.join(','.join(l) for l in w['legs'])}|{result['run']['at_utc']}"
            w["decision"] = {"id": hashlib.sha1(key.encode()).hexdigest()[:16], "at_utc": result["run"]["at_utc"],
                             "cutoff_status": cut.get(str(r["race_no"]), {}).get("status", "unknown"),
                             "price_basis": "morning-line", "status": "suggested",
                             "config_hash": result["run"]["config_hash"], "parser_version": card.get("parser_version"),
                             "code_version": result["run"]["code_version"]}
    return {"card": card, "raw": raw, "result": result, "cfg": cfg, "track_code": code, "notes": notes}
