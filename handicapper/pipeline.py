"""
One run of the engine on one card: parse (or load), merge the quick sheet, apply scratches, attach earlier
results, choose the track profile, score.  pick.py and the local web app (ui/server.py) both call run_card()
so the command line and the screen can never disagree.
"""
from __future__ import annotations

import copy
import json
import os

from brisnet_pp.parser import parse_pdf
from brisnet_pp.sheet import merge_sheet, parse_sheet
from .engine import load_config, resolve_track_code, score_card
from .results import apply_scratches, attach_day_bias, load_results, parse_scratch_spec

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(ROOT, "rules_config.json")


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
             budget3: float | None = None, budget4: float | None = None, race_no: int | None = None) -> dict:
    """Returns {"card": the card as scored (after scratches), "raw": the card before scratches, "result": picks,
    "cfg": config used, "track_code", "notes": [...]}."""
    card, notes = load_card(source)
    raw = copy.deepcopy(card)
    if sheet:
        notes.extend("sheet: " + n for n in merge_sheet(card, parse_sheet(sheet)))
    if scratch:
        notes.extend("scratch: " + n for n in apply_scratches(card, parse_scratch_spec(scratch)))
    if results:
        res = results if isinstance(results, dict) else load_results(results)
        notes.extend("results: " + n for n in attach_day_bias(card, res))
    if race_no:
        card["races"] = [r for r in card["races"] if r["race_no"] == race_no]
    base_cfg = load_config(config_path)
    code = track_profile or resolve_track_code(card, base_cfg)
    cfg = load_config(config_path, track_code=code)
    notes.append(f"track: {card.get('track')} ({code or 'unknown code'}); profile: {cfg['track_profile']}")
    if budget3 is not None:
        cfg["multirace"]["pick3"]["budget"] = budget3
    if budget4 is not None:
        cfg["multirace"]["pick4"]["budget"] = budget4
    result = score_card(card, cfg, multirace=multirace)
    if not result.get("track_code") and code:   # a card parsed before the parser recorded the code
        result["track_code"] = code
    # what this run was made from, so a picks.json on its own says which scratches and parser produced it
    result["scratches"] = scratch or ""
    result["parser_version"] = card.get("parser_version")
    result["run_notes"] = list(notes)
    return {"card": card, "raw": raw, "result": result, "cfg": cfg, "track_code": code, "notes": notes}
