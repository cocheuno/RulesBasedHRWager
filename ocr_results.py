#!/usr/bin/env python3
"""
Read result charts (PDF) and payout-page screenshots (PNG) into a results file.

    python ocr_results.py data/results-png/dmr1106y results/dmr1106y.results.json --card data/out/dmr1106y.card.json
    python ocr_results.py data/results-png/dmr1106y/r3.png results/dmr1106y.results.json      # one race
    python ocr_results.py data/results-png/bel1106y/20261106BELUSA1.pdf results/bel1106y.results.json

A chart PDF (Equibase/Brisnet, named r<N>.pdf or as downloaded, e.g. 20261106BELUSA1.pdf) is preferred over a
screenshot of the same race: it is text, complete (every finisher, final odds, calls, condition, comments) and
needs no OCR.  Screenshots are named r<N>.png and need an OCR engine.  Races already on file are left alone
unless --force, except that a chart always replaces an entry that came from a screenshot or was typed in.  Warnings (a name that does not match the card, a combo/name
disagreement) are printed and stored under each race's "ocr" block so the Desk can flag them.
Needs an OCR engine:  pip install rapidocr_onnxruntime
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from handicapper.ocr import read_screenshot   # noqa: E402
from brisnet_pp.chart import chart_to_result, parse_chart   # noqa: E402


def race_no_of(path: str) -> int | None:
    b = os.path.basename(path)
    m = re.match(r"^r(\d{1,2})\.(png|pdf)$", b, re.I) or re.search(r"USA(\d{1,2})\.pdf$", b, re.I)
    return int(m.group(1)) if m else None


def roster_from_card(card_path: str | None) -> dict:
    if not card_path or not os.path.exists(card_path):
        return {}
    card = json.load(open(card_path, encoding="utf-8"))
    return {"meta": {"track": card.get("track"), "date": card.get("date")},
            "races": {r["race_no"]: {h["pgm"]: h["name"] for h in r["horses"]} for r in card["races"]}}


def ocr_folder(src: str, results_path: str, card_path: str | None = None, force: bool = False) -> dict:
    if src.lower().endswith((".png", ".pdf")):
        files = [src]
    else:
        files = [p for p in glob.glob(os.path.join(src, "*")) if race_no_of(p)]
        # a chart beats a screenshot of the same race
        by_rn = {}
        for p in sorted(files, key=lambda p: (race_no_of(p), 0 if p.lower().endswith(".pdf") else 1)):
            by_rn.setdefault(race_no_of(p), p)
        files = [by_rn[k] for k in sorted(by_rn)]
    info = roster_from_card(card_path)
    if os.path.exists(results_path):
        data = json.load(open(results_path, encoding="utf-8"))
    else:
        data = {"track": info.get("meta", {}).get("track"), "date": info.get("meta", {}).get("date"), "_source": "OCR of payout-page screenshots", "races": []}
    have = {r["race_no"]: (r.get("source") or r.get("ocr", {}).get("source") or "manual") for r in data["races"]}
    done = []
    for p in files:
        rn = race_no_of(p)
        if rn is None:
            continue
        if rn in have and not force and not (p.lower().endswith(".pdf") and have[rn] != "chart"):
            continue   # already on file - unless a chart can replace a screenshot / typed entry
        if p.lower().endswith(".pdf"):
            charts = parse_chart(p)
            if not charts:
                continue
            race = chart_to_result(charts[0])
            race["race_no"] = rn
            race["ocr"] = {"names": [x["name"] for x in race.get("runners", [])], "confidence": 1.0, "warnings": [], "source": "chart"}
        else:
            race = read_screenshot(p, rn, info.get("races", {}).get(rn))
        data["races"] = [r for r in data["races"] if r["race_no"] != rn] + [race]
        done.append(race)
    data["races"].sort(key=lambda r: r["race_no"])
    with open(results_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    return {"path": results_path, "races": done}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="folder of r<N>.png screenshots, or one png")
    ap.add_argument("results", help="results/<card>.results.json to create or extend")
    ap.add_argument("--card", help="data/out/<card>.card.json for the name cross-check")
    ap.add_argument("--force", action="store_true", help="re-read races already on file")
    a = ap.parse_args()
    out = ocr_folder(a.src, a.results, a.card, a.force)
    for r in out["races"]:
        w = r["ocr"]["warnings"]
        print(f"R{r['race_no']}: finish {'/'.join(r['finish'])}" + (f", win ${r['win']:.2f}" if r.get("win") else "") +
              f", {len(r['exotics'])} pools, {r['ocr'].get('source', 'screenshot')}, confidence {r['ocr']['confidence']}" +
              (f", track {r['track_condition']}" if r.get("track_condition") else "") + (f"  WARN: {'; '.join(w)}" if w else ""))
    print(f"wrote {out['path']} ({len(out['races'])} races read)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
