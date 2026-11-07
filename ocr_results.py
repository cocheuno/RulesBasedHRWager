#!/usr/bin/env python3
"""
Read payout-page screenshots into a results file.

    python ocr_results.py data/results-png/dmr1106y results/dmr1106y.results.json --card data/out/dmr1106y.card.json
    python ocr_results.py data/results-png/dmr1106y/r3.png results/dmr1106y.results.json      # one race

Screenshots are named r<N>.png.  Existing races in the results file are replaced only with --force; otherwise
only races not yet on file are added.  Warnings (a name that does not match the card, a combo/name
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


def roster_from_card(card_path: str | None) -> dict:
    if not card_path or not os.path.exists(card_path):
        return {}
    card = json.load(open(card_path, encoding="utf-8"))
    return {"meta": {"track": card.get("track"), "date": card.get("date")},
            "races": {r["race_no"]: {h["pgm"]: h["name"] for h in r["horses"]} for r in card["races"]}}


def ocr_folder(src: str, results_path: str, card_path: str | None = None, force: bool = False) -> dict:
    files = [src] if src.lower().endswith(".png") else sorted(glob.glob(os.path.join(src, "r*.png")), key=lambda p: int(re.search(r"r(\d+)", os.path.basename(p)).group(1)))
    info = roster_from_card(card_path)
    if os.path.exists(results_path):
        data = json.load(open(results_path, encoding="utf-8"))
    else:
        data = {"track": info.get("meta", {}).get("track"), "date": info.get("meta", {}).get("date"), "_source": "OCR of payout-page screenshots", "races": []}
    have = {r["race_no"] for r in data["races"]}
    done = []
    for p in files:
        m = re.search(r"r(\d+)\.png$", os.path.basename(p), re.I)
        if not m:
            continue
        rn = int(m.group(1))
        if rn in have and not force:
            continue
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
              f", {len(r['exotics'])} pools, confidence {r['ocr']['confidence']}" + (f"  WARN: {'; '.join(w)}" if w else ""))
    print(f"wrote {out['path']} ({len(out['races'])} races read)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
