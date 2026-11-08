"""
Pre-race prediction snapshots: append-only, never overwritten.

`picks.json` is the *latest* run and is rewritten on every run (scratches, re-reads, the as-run re-score after the
charts arrive).  A snapshot is one run frozen at the moment it was made, so the question "what did the engine say
before the race?" has an answer that later runs cannot change.

    data/out/snapshots/<card>/<UTC time>_<kind>.picks.json

kind:  pre-race      made before any result for this card was on file: the run you could have bet from
       post-results  made after results were on file for some race (a re-run with late scratches, say): still an
                     honest run for the races whose results were not yet known, but labelled
       as-run        the retrospective re-score with the chart's actual field (Process results); never a bet

Each snapshot carries the run block from handicapper.pipeline.run_card (UTC time, scratches, parser version,
config hash, code version, source hash, which races had results on file) and the full sheets with every rule
contribution; the per-horse `features` dict is dropped to keep the file small (it is in the latest picks.json).
"""
from __future__ import annotations

import copy
import glob
import json
import os
from datetime import datetime, timezone

KINDS = ("pre-race", "post-results", "as-run")


def snapshot_dir(out_dir: str, card: str) -> str:
    return os.path.join(out_dir, "snapshots", card)


def write_snapshot(out_dir: str, card: str, result: dict, kind: str) -> str:
    """Write one immutable snapshot; returns its path.  A name clash (two runs in the same second) gets a suffix."""
    if kind not in KINDS:
        raise ValueError(f"snapshot kind must be one of {KINDS}, not {kind!r}")
    d = snapshot_dir(out_dir, card)
    os.makedirs(d, exist_ok=True)
    at = (result.get("run") or {}).get("at_utc") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stem = at.replace(":", "").replace("-", "") + "_" + kind
    path = os.path.join(d, stem + ".picks.json")
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(d, f"{stem}-{n}.picks.json")
    snap = copy.deepcopy(result)
    snap["snapshot"] = {"kind": kind, "at_utc": at, "file": os.path.basename(path)}
    for r in snap.get("races", []):
        for s in r.get("sheets", []):
            s.pop("features", None)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(snap, fh, indent=1, ensure_ascii=False, default=str)
    return path


def list_snapshots(out_dir: str, card: str) -> list[dict]:
    """Oldest first: [{file, path, kind, at_utc, scratches, parser_version, results_known}]."""
    out = []
    for p in sorted(glob.glob(os.path.join(snapshot_dir(out_dir, card), "*.picks.json"))):
        try:
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        sn, run = d.get("snapshot") or {}, d.get("run") or {}
        out.append({"file": os.path.basename(p), "path": p, "kind": sn.get("kind"), "at_utc": sn.get("at_utc"),
                    "scratches": d.get("scratches", run.get("scratches", "")), "parser_version": d.get("parser_version"),
                    "results_known": run.get("results_known", []), "config_hash": run.get("config_hash"),
                    "code_version": run.get("code_version")})
    return out


def latest_snapshot(out_dir: str, card: str, kind: str | None = "pre-race") -> dict | None:
    """The newest snapshot of the given kind (any kind when None), loaded; None when there is none."""
    snaps = [s for s in list_snapshots(out_dir, card) if kind is None or s["kind"] == kind]
    if not snaps:
        return None
    with open(snaps[-1]["path"], encoding="utf-8") as fh:
        return json.load(fh)
