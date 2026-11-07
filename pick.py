#!/usr/bin/env python3
"""
End-to-end: Brisnet Ultimate PPs PDF (or parsed JSON)  ->  1-3 horses per race.

    python pick.py card.pdf                      # parse + score, print report
    python pick.py card.pdf -o out/              # also write card.json, picks.json, picks.md
    python pick.py card.json --detail 2          # full rule-by-rule audit for every horse
    python pick.py --rules-doc > RULES.md        # print the rule catalog
    python pick.py card.pdf --config rules_config.json
    python pick.py card.json --budget4 48           # Pick 4 tickets shaped to a $48 budget
    python pick.py card.pdf --scratch "3:3, 8:4, 8:9" --results results/card.results.json   # scratches; day bias from earlier results
    python pick.py card.pdf --sheet cardq.pdf          # Brisnet Power Play sheet: key-race angles + Brisnet picks benchmark
    python backtest.py out/card.picks.json results/card.results.json                        # how did the rules do?
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from handicapper.engine import format_report, rules_doc  # noqa: E402
from handicapper.pipeline import run_card                # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("card", nargs="?", help="Brisnet Ultimate PPs PDF, or JSON produced by brisnet_pp.parser")
    ap.add_argument("-o", "--out", help="output directory for card.json / picks.json / picks.md")
    ap.add_argument("-c", "--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules_config.json"))
    ap.add_argument("--detail", type=int, default=1, help="0 wagering summary only, 1 summary + race tables (default), 2 summary + full audit")
    ap.add_argument("--rules-doc", action="store_true", help="print the rule catalog as markdown and exit")
    ap.add_argument("--race", type=int, help="only this race number")
    ap.add_argument("--scratch", help="scratched horses as race:program pairs, e.g. \"3:3, 4:6, 8:4, 8:9\" (also-eligibles draw in)")
    ap.add_argument("--results", help="results JSON for this card (results/<card>.results.json); earlier races feed the same-day bias rule P10")
    ap.add_argument("--sheet", help="Brisnet Power Play quick sheet PDF (<card>q.pdf): key-race angles (F16) and Brisnet's picks for the back-test")
    ap.add_argument("--track-profile", help="force a track profile from rules_config.json -> tracks (default: the track code read from the PP)")
    ap.add_argument("--no-multi", action="store_true", help="skip the Pick 3 / Pick 4 construction section")
    ap.add_argument("--budget3", type=float, help="override the Pick 3 budget in dollars (rules_config.json -> multirace.pick3.budget)")
    ap.add_argument("--budget4", type=float, help="override the Pick 4 budget in dollars (rules_config.json -> multirace.pick4.budget)")
    args = ap.parse_args()

    if args.rules_doc:
        print(rules_doc())
        return 0
    if not args.card:
        ap.error("card is required")
    out = run_card(args.card, scratch=args.scratch, sheet=args.sheet, results=args.results, config_path=args.config,
                   track_profile=args.track_profile, multirace=not args.no_multi, budget3=args.budget3, budget4=args.budget4,
                   race_no=args.race)
    for n in out["notes"]:
        print(n, file=sys.stderr)
    card, result = out["card"], out["result"]
    report = format_report(result, detail=args.detail)
    print(report)
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        base = os.path.splitext(os.path.basename(args.card))[0]
        with open(os.path.join(args.out, f"{base}.card.json"), "w", encoding="utf-8") as fh:
            json.dump(card, fh, indent=1, ensure_ascii=False)
        with open(os.path.join(args.out, f"{base}.picks.json"), "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1, ensure_ascii=False, default=str)
        with open(os.path.join(args.out, f"{base}.picks.md"), "w", encoding="utf-8") as fh:
            fh.write(format_report(result, detail=2))
        print(f"\nwrote {args.out}/{base}.card.json, {base}.picks.json, {base}.picks.md", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
