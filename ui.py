#!/usr/bin/env python3
"""
Race Day Desk: the local screen for pick.py.

    python ui.py              # runs in this window (Ctrl+C stops it); opens http://127.0.0.1:8765
    python ui.py start        # runs in the background and gives the prompt back
    python ui.py stop         # stops the background app
    python ui.py status
    python ui.py --port 9000 / --no-browser   (also accepted after "start")
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.server import ROOT, serve   # noqa: E402


def pid_path(root: str) -> str:
    return os.path.join(root, "data", "ui.pid")


def read_pid(root: str) -> dict | None:
    try:
        return json.load(open(pid_path(root), encoding="utf-8"))
    except Exception:
        return None


def alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/cards", timeout=1.5):
            return True
    except Exception:
        return False


def start(root: str, port: int, open_browser: bool) -> int:
    info = read_pid(root)
    if info and alive(info.get("port", port)):
        print(f"Race Day Desk is already running at http://127.0.0.1:{info['port']}/")
        return 0
    cmd = [sys.executable, os.path.abspath(__file__), "--root", root, "--port", str(port)] + ([] if open_browser else ["--no-browser"])
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    log = open(os.path.join(root, "data", "ui.log"), "ab")
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(cmd, stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    else:
        proc = subprocess.Popen(cmd, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    with open(pid_path(root), "w", encoding="utf-8") as fh:
        json.dump({"pid": proc.pid, "port": port}, fh)
    for _ in range(40):
        if alive(port):
            print(f"Race Day Desk started in the background at http://127.0.0.1:{port}/  (python ui.py stop to end it; log: data/ui.log)")
            return 0
        time.sleep(0.25)
    print("started, but the app did not answer within 10 s; see data/ui.log")
    return 1


def stop(root: str) -> int:
    info = read_pid(root)
    if not info:
        print("no background app recorded (data/ui.pid missing)")
        return 1
    port, pid = info.get("port", 8765), info.get("pid")
    try:   # graceful: the server shuts itself down
        urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/shutdown", data=b"{}", method="POST"), timeout=3).read()
    except Exception:
        pass
    for _ in range(20):
        if not alive(port):
            break
        time.sleep(0.25)
    if alive(port) and pid:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            else:
                os.kill(pid, 15)
        except Exception as e:
            print("could not stop process", pid, e)
            return 1
    try:
        os.remove(pid_path(root))
    except OSError:
        pass
    print("Race Day Desk stopped")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", choices=["run", "start", "stop", "status"], default="run")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--root", default=ROOT, help="repository folder (data/ and results/ live under it)")
    args = ap.parse_args()
    if args.action == "start":
        return start(args.root, args.port, not args.no_browser)
    if args.action == "stop":
        return stop(args.root)
    if args.action == "status":
        info = read_pid(args.root)
        port = info.get("port", args.port) if info else args.port
        print(f"running at http://127.0.0.1:{port}/" if alive(port) else "not running")
        return 0
    serve(args.root, port=args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
