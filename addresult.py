#!/usr/bin/env python3
"""
Add or replace one race in a results file, typed straight off the track's payout page.

    python addresult.py results/dmr1106y.results.json 3 8/3/1/4 win=9.40 place=8:5.40,3:6.80 show=8:3.00,3:4.40,1:2.60 \
        exacta=1:8/3:40.10 trifecta=0.5:8/3/1:79.20 superfecta=0.1:8/3/1/4:92.81 double=2:6/8:29.80 pick3=0.5:1/6/8:19.55

Arguments after the race number:
    8/3/1/4            finish order, program numbers (as many as the page shows; the superfecta gives the 4th)
    win=9.40           $2 win payoff of the winner
    place=8:5.40,3:6.80   $2 place payoffs, program:amount
    show=8:3.00,...    $2 show payoffs
    <pool>=<base>:<combo>:<payout>   any exotic: exacta, quinella, trifecta, superfecta, double, pick3, pick4, pick5...
Only the finish order is required.  The file is created if it does not exist (pass --track and --date the first time).
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("race_no", type=int)
    ap.add_argument("finish", help="finish order like 8/3/1/4")
    ap.add_argument("fields", nargs="*", help="win=.. place=.. show=.. <pool>=<base>:<combo>:<payout>")
    ap.add_argument("--track")
    ap.add_argument("--date")
    args = ap.parse_args()

    if os.path.exists(args.file):
        data = json.load(open(args.file, encoding="utf-8"))
    else:
        if not (args.track and args.date):
            ap.error("new file: pass --track and --date")
        data = {"track": args.track, "date": args.date, "_source": "track payout pages, typed with addresult.py", "races": []}
    race = {"race_no": args.race_no, "finish": [p.strip() for p in args.finish.split("/") if p.strip()], "exotics": []}
    for f in args.fields:
        if "=" not in f:
            ap.error(f"bad field {f!r}")
        key, val = f.split("=", 1)
        key = key.strip().lower()
        if key == "win":
            race["win"] = float(val)
        elif key in ("place", "show"):
            race[key] = {k.strip(): float(v) for k, v in (x.split(":") for x in val.split(",") if x)}
        else:
            try:
                base, combo, payout = val.rsplit(":", 2)
            except ValueError:
                ap.error(f"{key}: expected <base>:<combo>:<payout>, got {val!r}")
            race["exotics"].append({"type": key.upper().replace("SUPER", "SUPERFECTA") if key == "super" else key.upper(),
                                    "base": float(base), "combo": combo, "payout": float(payout)})
    data["races"] = [r for r in data["races"] if r["race_no"] != args.race_no] + [race]
    data["races"].sort(key=lambda r: r["race_no"])
    with open(args.file, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    print(f"{args.file}: race {args.race_no} saved; {len(data['races'])} races on file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
