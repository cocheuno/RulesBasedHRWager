"""
Race Day Desk: a local web app on the Python standard library.

    python ui.py                 # http://127.0.0.1:8765

Serves ui/static/ and a JSON API that calls the engine directly (handicapper.pipeline.run_card), so the
screen and pick.py always agree.  Files live where the command line puts them:

    data/pps/<card>.pdf, data/pps/<card>q.pdf      PPs and quick sheet (ignored by git)
    data/out/<card>.card.json / .picks.json / .picks.md
    data/results-png/<card>/r<N>.png              result screenshots
    data/cards/<card>.json                        UI state: scratches, runs
    results/<card>.results.json, <card>.backtest.md

API
    GET  /api/cards                         cards on disk and what each has
    GET  /api/cards/<card>                  roster, latest picks, results, back-test, wager evaluation, state
    POST /api/cards/<card>/run              {"scratches": "2:10, 4:2"} -> run the engine, write data/out, return the card payload
    PUT  /api/cards/<card>/scratches        {"scratches": "..."} -> save without running
    POST /api/cards/<card>/results          {"race_no", "finish", "win", "place", "show", "exotics"} -> results file
    POST /api/cards/<card>/ocr              {"race_no": n?, "force": bool} -> read screenshot(s) into the results file
    POST /api/cards/<card>/process          OCR any screenshot not yet on file, then back-test + wager evaluation -> results/<card>.backtest.md
    POST /api/upload  (multipart)           fields card, kind (pp|sheet|png), race_no (png), file
    GET  /api/analysis                      roll-up across every card with results
    GET  /png/<card>/<file>                 a result screenshot
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from handicapper.engine import format_report, load_config   # noqa: E402
from handicapper.pipeline import run_card                     # noqa: E402
from handicapper.results import backtest, format_backtest, load_results   # noqa: E402
from handicapper.wagering import evaluate_card, format_evaluation, rollup  # noqa: E402
from ocr_results import ocr_folder   # noqa: E402

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
CARD_RE = re.compile(r"^[a-z0-9_-]{3,24}$", re.I)


class Desk:
    """All file-system and engine work, independent of HTTP so it can be tested directly."""

    def __init__(self, root: str = ROOT):
        self.root = root
        self.pps = os.path.join(root, "data", "pps")
        self.out = os.path.join(root, "data", "out")
        self.pngs = os.path.join(root, "data", "results-png")
        self.states = os.path.join(root, "data", "cards")
        self.results = os.path.join(root, "results")
        self.config = os.path.join(root, "rules_config.json")
        for d in (self.pps, self.out, self.pngs, self.states, self.results):
            os.makedirs(d, exist_ok=True)
        self.lock = threading.Lock()

    # ---------------------------------------------------------------- files
    def files(self, card: str) -> dict:
        pp = os.path.join(self.pps, f"{card}.pdf")
        sheet_names = [f"{card[:-1]}q.pdf" if card.endswith("y") else "", f"{card}q.pdf"]
        sheet = next((os.path.join(self.pps, s) for s in sheet_names if s and os.path.exists(os.path.join(self.pps, s))), None)
        pngdir = os.path.join(self.pngs, card)
        pngs = sorted(os.path.basename(p) for p in glob.glob(os.path.join(pngdir, "r*.png")))
        return {"pp": pp if os.path.exists(pp) else None, "sheet": sheet,
                "card_json": self._opt(os.path.join(self.out, f"{card}.card.json")),
                "picks_json": self._opt(os.path.join(self.out, f"{card}.picks.json")),
                "results": self._opt(os.path.join(self.results, f"{card}.results.json")),
                "backtest_md": self._opt(os.path.join(self.results, f"{card}.backtest.md")),
                "pngs": pngs}

    @staticmethod
    def _opt(p):
        return p if os.path.exists(p) else None

    def cards(self) -> list[dict]:
        names = set()
        for p in glob.glob(os.path.join(self.pps, "*.pdf")):
            stem = os.path.splitext(os.path.basename(p))[0]
            if not stem.endswith("q"):
                names.add(stem)
        for p in glob.glob(os.path.join(self.out, "*.card.json")):
            names.add(os.path.basename(p)[:-len(".card.json")])
        for p in glob.glob(os.path.join(self.results, "*.results.json")):
            names.add(os.path.basename(p)[:-len(".results.json")])
        out = []
        for c in sorted(names):
            f = self.files(c)
            st = self.state(c)
            info = {"card": c, "has_pp": bool(f["pp"]), "has_sheet": bool(f["sheet"]), "has_picks": bool(f["picks_json"]),
                    "has_results": bool(f["results"]), "pngs": len(f["pngs"]), "track": None, "date": None, "runs": len(st.get("runs", []))}
            src = f["card_json"] or f["picks_json"]
            if src:
                try:
                    j = json.load(open(src, encoding="utf-8"))
                    info["track"], info["date"], info["track_code"] = j.get("track"), j.get("date"), j.get("track_code")
                except Exception:
                    pass
            out.append(info)
        out.sort(key=lambda x: (x["date"] or "", x["card"]), reverse=True)
        return out

    # ---------------------------------------------------------------- state
    def state(self, card: str) -> dict:
        p = os.path.join(self.states, f"{card}.json")
        if os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
        return {"card": card, "scratches": "", "runs": [], "activity": []}

    def save_state(self, st: dict) -> None:
        with open(os.path.join(self.states, f"{st['card']}.json"), "w", encoding="utf-8") as fh:
            json.dump(st, fh, indent=1)

    def log(self, st: dict, step: str, outcome: str) -> None:
        st.setdefault("activity", []).append({"at": datetime.now().isoformat(timespec="seconds"), "step": step, "outcome": outcome})
        st["activity"] = st["activity"][-50:]

    # ---------------------------------------------------------------- engine
    def run(self, card: str, scratches: str | None = None) -> dict:
        f = self.files(card)
        source = f["pp"] or f["card_json"]
        if not source:
            raise FileNotFoundError(f"no PDF or card.json for {card}: put the PPs at data/pps/{card}.pdf")
        st = self.state(card)
        if scratches is not None:
            st["scratches"] = scratches
        with self.lock:
            # parse once and cache the raw card so the roster (with scratched horses) is always available
            if f["pp"] and not f["card_json"]:
                out = run_card(f["pp"], config_path=self.config, multirace=False)
                with open(os.path.join(self.out, f"{card}.card.json"), "w", encoding="utf-8") as fh:
                    json.dump(out["raw"], fh, indent=1, ensure_ascii=False)
            cj = os.path.join(self.out, f"{card}.card.json")
            out = run_card(cj, scratch=st.get("scratches") or None, sheet=f["sheet"], results=f["results"], config_path=self.config)
            result = out["result"]
            with open(os.path.join(self.out, f"{card}.picks.json"), "w", encoding="utf-8") as fh:
                json.dump(result, fh, indent=1, ensure_ascii=False, default=str)
            with open(os.path.join(self.out, f"{card}.picks.md"), "w", encoding="utf-8") as fh:
                fh.write(format_report(result, detail=2))
        st.setdefault("runs", []).append({"at": datetime.now().isoformat(timespec="seconds"), "scratches": st.get("scratches", ""),
                                          "profile": result.get("track_profile"), "notes": out["notes"]})
        self.log(st, "Run picks", f"{len(result['races'])} races scored, profile {result.get('track_profile')}" +
                 (f", scratches: {st['scratches']}" if st.get("scratches") else ""))
        self.save_state(st)
        return self.payload(card)

    def payload(self, card: str) -> dict:
        f = self.files(card)
        st = self.state(card)
        roster, meta = [], {}
        if f["card_json"]:
            cj = json.load(open(f["card_json"], encoding="utf-8"))
            meta = {"track": cj.get("track"), "date": cj.get("date"), "track_code": cj.get("track_code")}
            for r in cj["races"]:
                roster.append({"race_no": r["race_no"], "class_text": r.get("class_text"), "distance_text": r.get("distance_text"),
                               "surface": r.get("surface"), "post_time": r.get("post_time"), "wagers": r.get("wagers"),
                               "horses": [{"pgm": h["pgm"], "post": h.get("post"), "name": h["name"], "ml_odds": h.get("ml_odds"),
                                           "run_style": h.get("run_style"), "speed_pts": h.get("speed_pts"), "entry_status": h.get("entry_status"),
                                           "jockey": h.get("jockey"), "trainer": h.get("trainer")} for h in r["horses"]]})
        picks = json.load(open(f["picks_json"], encoding="utf-8")) if f["picks_json"] else None
        results = load_results(f["results"]) if f["results"] else None
        bt = ev = None
        if picks and results:
            bt = backtest(picks, results)
            ev = evaluate_card(picks, results, load_config(self.config)["wagering"])
        return {"card": card, "meta": meta, "files": {k: (bool(v) if k != "pngs" else v) for k, v in f.items()},
                "state": st, "roster": roster, "picks": picks, "results": results, "backtest": bt, "evaluation": ev}

    # ---------------------------------------------------------------- results
    def save_result(self, card: str, race: dict) -> dict:
        p = os.path.join(self.results, f"{card}.results.json")
        if os.path.exists(p):
            data = json.load(open(p, encoding="utf-8"))
        else:
            meta = self.payload(card)["meta"]
            data = {"track": meta.get("track"), "date": meta.get("date"), "_source": "entered in Race Day Desk", "races": []}
        rn = int(race["race_no"])
        entry = {"race_no": rn, "finish": [str(x).strip() for x in race.get("finish", []) if str(x).strip()],
                 "exotics": [{"type": e["type"].upper(), "base": float(e["base"]), "combo": e["combo"], "payout": float(e["payout"])}
                             for e in race.get("exotics", []) if e.get("combo") and e.get("payout") not in (None, "")]}
        if race.get("win") not in (None, ""):
            entry["win"] = float(race["win"])
        for k in ("place", "show"):
            if race.get(k):
                entry[k] = {str(a): float(b) for a, b in race[k].items() if b not in (None, "")}
        data["races"] = [r for r in data["races"] if r["race_no"] != rn] + [entry]
        data["races"].sort(key=lambda r: r["race_no"])
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        st = self.state(card)
        self.log(st, f"Result R{rn}", f"finish {'/'.join(entry['finish'])}" + (f", win ${entry['win']:.2f}" if "win" in entry else ""))
        self.save_state(st)
        return self.payload(card)

    def ocr(self, card: str, race_no: int | None = None, force: bool = False) -> dict:
        """Read the card's payout screenshots into results/<card>.results.json (only races not yet on file unless force)."""
        f = self.files(card)
        src = os.path.join(self.pngs, card, f"r{race_no}.png") if race_no else os.path.join(self.pngs, card)
        if race_no and not os.path.exists(src):
            raise FileNotFoundError(f"no screenshot r{race_no}.png for {card}")
        out = ocr_folder(src, os.path.join(self.results, f"{card}.results.json"), f["card_json"], force)
        st = self.state(card)
        for r in out["races"]:
            w = r["ocr"]["warnings"]
            self.log(st, f"OCR R{r['race_no']}", f"finish {'/'.join(r['finish'])}, {len(r['exotics'])} pools" + (f"; CHECK: {'; '.join(w)}" if w else ""))
        self.save_state(st)
        return self.payload(card)

    def process(self, card: str) -> dict:
        f = self.files(card)
        if f["pngs"]:
            self.ocr(card)
        pl = self.payload(card)
        if not (pl["picks"] and pl["results"]):
            raise ValueError("needs a run (picks) and at least one race result (a screenshot r<N>.png or an entered result)")
        text = "# " + card + "\n\n" + format_backtest(pl["backtest"]) + "\n\n" + format_evaluation(pl["evaluation"])
        with open(os.path.join(self.results, f"{card}.backtest.md"), "w", encoding="utf-8") as fh:
            fh.write(text)
        st = self.state(card)
        s = pl["backtest"]["summary"]
        self.log(st, "Process results", f"top pick won {s['top_pick_wins']}/{s['races']}, winner in top 3 {s['winner_in_top3']}/{s['races']}; "
                 f"wagers {pl['evaluation']['totals']['hits']}/{pl['evaluation']['totals']['bets']} hit")
        self.save_state(st)
        pl["report"] = text
        return pl

    # ---------------------------------------------------------------- analysis
    def analysis(self) -> dict:
        cfg = load_config(self.config)["wagering"]
        evals, cards, rules = [], [], {}
        bench = {"races": 0, "engine_wins": 0, "brisnet_wins": 0, "brisnet_top3": 0, "best_bets": 0, "best_bet_wins": 0}
        for c in self.cards():
            f = self.files(c["card"])
            if not (f["picks_json"] and f["results"]):
                continue
            picks = json.load(open(f["picks_json"], encoding="utf-8"))
            res = load_results(f["results"])
            bt = backtest(picks, res)
            ev = evaluate_card(picks, res, cfg)
            ev["card_code"], ev["track_code"] = c["card"], picks.get("track_code") or c.get("track_code")
            evals.append(ev)
            s = bt["summary"]
            cards.append({"card": c["card"], "track": ev["track_code"], "date": picks.get("date"), "races": s["races"],
                          "top_pick_wins": s["top_pick_wins"], "winner_in_top3": s["winner_in_top3"],
                          "bets": ev["totals"]["bets"], "hits": ev["totals"]["hits"], "cost": ev["totals"]["cost"], "ret": ev["totals"]["ret"],
                          "multirace": {k: v.get("hit") for k, v in bt["multirace"].items() if v.get("known")}})
            for st in bt["rules"]:
                k = (st["rule"], st["sign"])
                d = rules.setdefault(k, {"rule": st["rule"], "sign": st["sign"], "fired": 0, "won": 0, "itm": 0})
                d["fired"] += st["fired"]; d["won"] += st["won"]; d["itm"] += st["itm"]
            if s.get("brisnet_races"):
                bench["races"] += s["brisnet_races"]; bench["brisnet_wins"] += s["brisnet_pick_wins"]; bench["brisnet_top3"] += s["brisnet_top3"]
                bench["best_bets"] += s["brisnet_best_bets"]; bench["best_bet_wins"] += s["brisnet_best_bet_wins"]
                bench["engine_wins"] += sum(1 for r in bt["races"] if r.get("brisnet_pick") and r["top_pick_won"])
        rule_rows = sorted(rules.values(), key=lambda d: (-d["fired"], d["rule"]))
        for d in rule_rows:
            d["win_pct"] = round(100.0 * d["won"] / d["fired"], 1) if d["fired"] else 0
            d["itm_pct"] = round(100.0 * d["itm"] / d["fired"], 1) if d["fired"] else 0
        rows = []
        for ev in evals:
            for x in ev["rows"]:
                rows.append(dict(x, card=ev["card_code"], track=ev["track_code"], date=ev.get("date")))
        return {"rollup": rollup(evals) if evals else None, "cards": cards, "rules": rule_rows, "rows": rows, "benchmark": bench, "unit": cfg["unit"]}

    # ---------------------------------------------------------------- uploads
    def save_upload(self, card: str, kind: str, filename: str, data: bytes, race_no: int | None = None) -> dict:
        if not CARD_RE.match(card):
            raise ValueError("card code must be letters/digits, e.g. dmr1106y")
        if kind == "pp":
            path = os.path.join(self.pps, f"{card}.pdf")
        elif kind == "sheet":
            path = os.path.join(self.pps, f"{card[:-1]}q.pdf" if card.endswith("y") else f"{card}q.pdf")
        elif kind == "png":
            if not race_no:
                m = re.search(r"r?(\d{1,2})", os.path.splitext(filename)[0])
                race_no = int(m.group(1)) if m else None
            if not race_no:
                raise ValueError("png needs a race number (name it r3.png or pass race_no)")
            os.makedirs(os.path.join(self.pngs, card), exist_ok=True)
            path = os.path.join(self.pngs, card, f"r{race_no}.png")
        else:
            raise ValueError("kind must be pp, sheet or png")
        with open(path, "wb") as fh:
            fh.write(data)
        if kind == "pp":   # a new PP file invalidates the cached parse
            for p in (os.path.join(self.out, f"{card}.card.json"),):
                if os.path.exists(p):
                    os.remove(p)
        st = self.state(card)
        self.log(st, f"Load {kind}", os.path.relpath(path, self.root))
        self.save_state(st)
        return {"saved": os.path.relpath(path, self.root)}


# --------------------------------------------------------------------------- HTTP
def parse_multipart(body: bytes, ctype: str) -> tuple[dict, list]:
    m = re.search(r"boundary=([^;]+)", ctype)
    if not m:
        raise ValueError("no multipart boundary")
    boundary = m.group(1).strip().strip('"').encode()
    fields, files = {}, []
    for part in body.split(b"--" + boundary):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        head, _, content = part.partition(b"\r\n\r\n")
        headers = head.decode("utf-8", "replace")
        name = re.search(r'name="([^"]*)"', headers)
        fname = re.search(r'filename="([^"]*)"', headers)
        if not name:
            continue
        if fname:
            files.append({"field": name.group(1), "filename": os.path.basename(fname.group(1)), "data": content})
        else:
            fields[name.group(1)] = content.decode("utf-8", "replace")
    return fields, files


class Handler(SimpleHTTPRequestHandler):
    desk: Desk = None

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC, **kw)

    def log_message(self, fmt, *args):   # quieter console: API calls and errors only
        line = fmt % args if args else fmt
        if "/api/" in line or "code 5" in line:
            sys.stderr.write("%s %s\n" % (time.strftime("%H:%M:%S"), line))

    def _json(self, obj, status=200):
        data = json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path == "/api/cards":
                return self._json(self.desk.cards())
            m = re.fullmatch(r"/api/cards/([^/]+)", u.path)
            if m:
                return self._json(self.desk.payload(unquote(m.group(1))))
            if u.path == "/api/analysis":
                return self._json(self.desk.analysis())
            m = re.fullmatch(r"/png/([^/]+)/(r\d{1,2}\.png)", u.path)
            if m:
                p = os.path.join(self.desk.pngs, unquote(m.group(1)), m.group(2))
                if not os.path.exists(p):
                    return self._json({"error": "no such screenshot"}, 404)
                data = open(p, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            if u.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return None
            if u.path == "/":
                self.path = "/index.html"
            return super().do_GET()
        except Exception as e:  # report, never crash the server
            traceback.print_exc()
            return self._json({"error": str(e)}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            if u.path == "/api/upload":
                fields, files = parse_multipart(self._body(), self.headers.get("Content-Type", ""))
                out = []
                for f in files:
                    rn = fields.get("race_no")
                    out.append(self.desk.save_upload(fields.get("card", ""), fields.get("kind", ""), f["filename"], f["data"],
                                                     int(rn) if rn else None))
                return self._json({"saved": [o["saved"] for o in out]})
            body = self._body()
            payload = json.loads(body) if body else {}
            m = re.fullmatch(r"/api/cards/([^/]+)/(run|results|process|ocr)", u.path)
            if m:
                card, action = unquote(m.group(1)), m.group(2)
                if action == "run":
                    return self._json(self.desk.run(card, payload.get("scratches")))
                if action == "ocr":
                    rn = payload.get("race_no")
                    return self._json(self.desk.ocr(card, int(rn) if rn else None, bool(payload.get("force"))))
                if action == "results":
                    return self._json(self.desk.save_result(card, payload))
                if action == "process":
                    return self._json(self.desk.process(card))
            return self._json({"error": "unknown endpoint"}, 404)
        except Exception as e:
            traceback.print_exc()
            return self._json({"error": str(e)}, 400)

    def do_PUT(self):
        u = urlparse(self.path)
        try:
            m = re.fullmatch(r"/api/cards/([^/]+)/scratches", u.path)
            if m:
                payload = json.loads(self._body() or b"{}")
                st = self.desk.state(unquote(m.group(1)))
                st["scratches"] = payload.get("scratches", "")
                self.desk.save_state(st)
                return self._json({"ok": True, "scratches": st["scratches"]})
            return self._json({"error": "unknown endpoint"}, 404)
        except Exception as e:
            traceback.print_exc()
            return self._json({"error": str(e)}, 400)


def make_server(root: str = ROOT, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    Handler.desk = Desk(root)
    return ThreadingHTTPServer((host, port), Handler)


def serve(root: str = ROOT, port: int = 8765, open_browser: bool = True) -> None:
    srv = make_server(root, port=port)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"Race Day Desk at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
