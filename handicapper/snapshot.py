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
import re
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


def _order_key(path: str) -> tuple:
    """Oldest first: by timestamp, then by the same-second suffix (stem.picks.json is the first run, stem-2 the second ...)."""
    name = os.path.basename(path)[: -len(".picks.json")]
    m = re.match(r"^(.*?)(?:-(\d+))?$", name)
    return (m.group(1), int(m.group(2) or 1))


def list_snapshots(out_dir: str, card: str) -> list[dict]:
    """Oldest first: [{file, path, kind, at_utc, scratches, parser_version, results_known}]."""
    out = []
    for p in sorted(glob.glob(os.path.join(snapshot_dir(out_dir, card), "*.picks.json")), key=_order_key):
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


def pre_race_by_race(out_dir: str, card: str, results: dict | None = None, tz: str | None = None,
                     margin_minutes: float = 2) -> dict | None:
    """The pre-race prediction per race: for each race the newest run that did not have that race's result on
    file when it was made (and is not an as-run re-score).  A run made late in the day or the next day is a
    pre-race prediction all the same: it uses only the PPs and the scratches, which are public before post, so
    the data is not compromised by the hour it was made.  The clock is a *label*, never a gate: each race's entry
    says whether its run was made before the race's cutoff (the chart's actual off time with the track timezone,
    else the scheduled post, else unknown) with a margin of `margin_minutes`.  Races where every run already knew
    the result are the only ones excluded.  Returns a composite picks dict with a `timing` block, or None."""
    from .timing import cutoff_status, off_at_utc, parse_utc, post_at_utc
    metas = list_snapshots(out_dir, card)
    if not metas:
        return None
    snaps = []
    for m in metas:
        with open(m["path"], encoding="utf-8") as fh:
            snaps.append(json.load(fh))
    by_no = {r["race_no"]: r for r in (results or {}).get("races", [])}
    race_nos = sorted({r["race_no"] for s in snaps for r in s.get("races", [])})
    chosen, per_race, excluded = {}, {}, []
    for rn in race_nos:
        best = None
        for s in snaps:                                   # oldest first: the last eligible run is the newest
            race = next((r for r in s.get("races", []) if r["race_no"] == rn), None)
            run = s.get("run") or {}
            if race is None or (s.get("snapshot") or {}).get("kind") == "as-run" or rn in (run.get("results_known") or []):
                continue                                  # knew this race's result, or re-scored with the chart's field
            run_at = parse_utc(run.get("at_utc") or (s.get("snapshot") or {}).get("at_utc"))
            res = by_no.get(rn) or {}
            off = off_at_utc(s.get("date"), res.get("off_at"), tz)
            rec = (run.get("cutoffs") or {}).get(str(rn)) or {}
            post = parse_utc(rec.get("post_at_utc")) or post_at_utc(s.get("date"), race.get("post_time"))
            cutoff = off or post
            status = cutoff_status(run_at, cutoff, margin_minutes)
            best = (s, status, "off" if off else ("scheduled" if post else "none"))
        if best is None:
            excluded.append(rn)
            continue
        chosen[rn] = best[0]
        per_race[str(rn)] = {"file": best[0]["snapshot"]["file"], "at_utc": best[0]["snapshot"]["at_utc"], "status": best[1],
                             "basis": best[2], "scratches": best[0].get("scratches", "")}
    if not chosen:
        return None
    first = chosen[min(chosen)]
    comp = copy.deepcopy(first)
    comp["races"] = [copy.deepcopy(next(r for r in chosen[rn]["races"] if r["race_no"] == rn)) for rn in sorted(chosen)]
    comp["scratches"] = chosen[max(chosen)].get("scratches", "")
    st = [v["status"] for v in per_race.values()]
    comp["timing"] = {"label": ("before-cutoff" if st and all(x == "before-cutoff" for x in st) else
                                "unverified" if st and all(x == "unknown" for x in st) else
                                "after-cutoff" if st and all(x == "after-cutoff" for x in st) else "mixed"),
                      "before": st.count("before-cutoff"), "after": st.count("after-cutoff"), "unknown": st.count("unknown"),
                      "per_race": per_race, "excluded": excluded, "margin_minutes": margin_minutes, "track_timezone": tz}
    comp["snapshot"] = {"kind": "composite", "at_utc": max(v["at_utc"] for v in per_race.values()),
                        "file": ", ".join(sorted({v["file"] for v in per_race.values()}))}
    from racing_dudes.reader import card_benchmark     # Racing Dudes: the newest page for the date (a benchmark)
    return card_benchmark(out_dir, card, comp)


def latest_snapshot(out_dir: str, card: str, kind: str | None = "pre-race") -> dict | None:
    """The newest snapshot of the given kind (any kind when None), loaded; None when there is none."""
    snaps = [s for s in list_snapshots(out_dir, card) if kind is None or s["kind"] == kind]
    if not snaps:
        return None
    with open(snaps[-1]["path"], encoding="utf-8") as fh:
        return json.load(fh)
