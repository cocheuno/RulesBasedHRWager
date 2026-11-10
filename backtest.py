#!/usr/bin/env python3
"""
Join a picks.json (written by pick.py -o) with a results file and report how the rules did.

    python backtest.py out/dmr1106y.picks.json results/dmr1106y.results.json
    python backtest.py out/*.picks.json results/*.results.json      # several cards: pass pairs in matching order
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from handicapper.results import backtest, format_backtest, load_results   # noqa: E402
from handicapper.wagering import evaluate_card, format_evaluation, format_rollup, rollup   # noqa: E402
from handicapper.engine import load_config   # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 2 or len(argv) % 2:
        print(__doc__)
        return 2
    half = len(argv) // 2
    cfg = load_config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules_config.json"))
    reports, evals = [], []
    for p_path, r_path in zip(argv[:half], argv[half:]):
        picks = json.load(open(p_path, encoding="utf-8"))
        res = load_results(r_path)
        bt = backtest(picks, res)
        ev = evaluate_card(picks, res, cfg["wagering"])
        evals.append(ev)
        reports.append(f"## {os.path.basename(p_path)}\n\n" + format_backtest(bt) + "\n\n" + format_evaluation(ev))
    print("\n\n".join(reports))
    if evals:
        print("\n\n" + format_rollup(rollup(evals)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
