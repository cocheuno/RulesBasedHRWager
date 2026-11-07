#!/usr/bin/env python3
"""
Race Day Desk: the local screen for pick.py.

    python ui.py              # opens http://127.0.0.1:8765 in your browser
    python ui.py --port 9000
    python ui.py --no-browser
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.server import ROOT, serve   # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--root", default=ROOT, help="repository folder (data/ and results/ live under it)")
    args = ap.parse_args()
    serve(args.root, port=args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
