"""Append-only prediction history with explicit timing evidence.

A missing result is never evidence of a before-post prediction. New runs need
aware `post_at_utc` timestamps on every selected race to qualify as pre-race.
Legacy pre-race labels are retained on disk but evaluated as timing-unverified.
"""
from __future__ import annotations

import copy
import glob
import json
import os
import re
from datetime import datetime, timezone, timedelta

KINDS = ("pre-race", "post-results", "as-run", "timing-unverified", "retrospective")


def aware_time(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None
    except (ValueError, TypeError, AttributeError):
        return None


def timing_evidence(card: dict, at: datetime, results_known: list) -> dict:
    """Use explicit offset-aware post times; never guess a timezone from PP text."""
    races = []
    for r in card.get("races", []):
        post = aware_time(r.get("post_at_utc"))
        state = "retrospective" if r["race_no"] in results_known or (post and post <= at) else (
            "before-post" if post else "unverified")
        races.append({"race_no": r["race_no"], "post_at_utc": post.isoformat() if post else None, "state": state})
    # A card more than a day old is historical in every supported local timezone.
    try:
        old_card = datetime.fromisoformat(card["date"]).date() < (at - timedelta(days=1)).date()
    except (KeyError, ValueError, TypeError):
        old_card = False
    status = ("retrospective" if old_card or any(r["state"] == "retrospective" for r in races) else
              "verified-before-post" if races and all(r["state"] == "before-post" for r in races) else "unverified")
    return {"status": status, "races": races}


def prediction_kind(result: dict, requested: str | None = None) -> str:
    if requested is not None and requested not in KINDS:
        raise ValueError(f"unknown snapshot kind {requested!r}")
    if requested in ("as-run", "retrospective"):
        return requested
    run = result.get("run") or {}
    if run.get("results_known"):
        return "post-results"
    status = (run.get("timing") or {}).get("status")
    if status == "retrospective":
        return "retrospective"
    if status == "verified-before-post":
        return "pre-race"
    return "timing-unverified"


def evaluation_basis(result: dict) -> str:
    """Legacy labels alone cannot establish prospective performance."""
    run = result.get("run") or {}
    kind = (result.get("snapshot") or {}).get("kind") or run.get("kind")
    if kind in ("as-run", "post-results", "retrospective") or run.get("results_known"):
        return "retrospective"
    at = aware_time(run.get("at_utc"))
    timing = run.get("timing") or {}
    evidence = timing.get("races") or []
    numbers = [r["race_no"] for r in result.get("races", [])]
    posts = [aware_time(r.get("post_at_utc")) for r in evidence]
    if (at and numbers and sorted(numbers) == sorted(r["race_no"] for r in evidence)
            and timing.get("status") == "verified-before-post"
            and all(p and p > at for p in posts)):
        return "verified-pre-race"
    return "timing-unverified"


def snapshot_dir(out_dir: str, card: str) -> str:
    return os.path.join(out_dir, "snapshots", card)


def write_snapshot(out_dir: str, card: str, result: dict, kind: str | None = None) -> str:
    kind = prediction_kind(result, kind)
    d = snapshot_dir(out_dir, card)
    os.makedirs(d, exist_ok=True)
    at = (result.get("run") or {}).get("at_utc") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    stem = at.replace(":", "").replace("-", "") + "_" + kind
    snap = copy.deepcopy(result)
    for race in snap.get("races", []):
        for sheet in race.get("sheets", []):
            sheet.pop("features", None)
    n = 1
    while True:
        path = os.path.join(d, stem + (f"-{n}" if n > 1 else "") + ".picks.json")
        try:
            # Exclusive creation closes the existence-check/write race between writers.
            with open(path, "x", encoding="utf-8") as fh:
                snap["snapshot"] = {"kind": kind, "at_utc": at, "sequence": n, "file": os.path.basename(path)}
                snap.setdefault("run", {})["kind"] = kind
                json.dump(snap, fh, indent=1, ensure_ascii=False, default=str)
            return path
        except FileExistsError:
            n += 1


def list_snapshots(out_dir: str, card: str) -> list[dict]:
    out = []
    for p in glob.glob(os.path.join(snapshot_dir(out_dir, card), "*.picks.json")):
        try:
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        sn, run = d.get("snapshot") or {}, d.get("run") or {}
        suffix = re.search(r"-(\d+)\.picks\.json$", os.path.basename(p))
        out.append({"file": os.path.basename(p), "path": p, "kind": sn.get("kind"), "at_utc": sn.get("at_utc"),
                    "sequence": sn.get("sequence", int(suffix.group(1)) if suffix else 1), "basis": evaluation_basis(d),
                    "scratches": d.get("scratches", run.get("scratches", "")), "parser_version": d.get("parser_version"),
                    "results_known": run.get("results_known", []), "config_hash": run.get("config_hash"),
                    "code_version": run.get("code_version")})
    out.sort(key=lambda s: (aware_time(s["at_utc"]) or datetime.min.replace(tzinfo=timezone.utc), s["sequence"], s["file"]))
    return out


def latest_snapshot(out_dir: str, card: str, kind: str | None = "pre-race", *, basis: str | None = None) -> dict | None:
    snaps = [s for s in list_snapshots(out_dir, card) if (kind is None or s["kind"] == kind)
             and (basis is None or s["basis"] == basis)]
    if not snaps:
        return None
    with open(snaps[-1]["path"], encoding="utf-8") as fh:
        return json.load(fh)
