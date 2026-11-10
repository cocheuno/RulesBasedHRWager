"""
Race Day Desk: a local web app on the Python standard library.

    python ui.py                 # http://127.0.0.1:8765

Serves ui/static/ and a JSON API that calls the engine directly (handicapper.pipeline.run_card), so the
screen and pick.py always agree.  Files live where the command line puts them:

    data/pps/<card>.pdf, data/pps/<card>q.pdf      PPs and quick sheet (ignored by git)
    data/out/<card>.card.json / .picks.json / .picks.md   (latest run)
    data/out/snapshots/<card>/<UTC>_<kind>.picks.json     (every run, append-only: pre-race / post-results / as-run)
    data/results-png/<card>/r<N>.png              result screenshots
    data/cards/<card>.json                        UI state: scratches, runs
    results/<card>.results.json, <card>.backtest.md

API
    GET  /api/cards                         cards on disk and what each has
    GET  /api/cards/<card>                  roster, latest picks, results, back-test, wager evaluation, state
    GET  /api/status                        {"started", "parser_version", "code_changed", "changed_files"}: the code on
                                            disk is newer than the running app (stop/start it)
    POST /api/cards/<card>/run              {"scratches": "2:10, 4:2", "reparse": false} -> run the engine (re-reading the PDF when
                                            asked, when it is newer than the cached card, or when the parser changed), write data/out
    PUT  /api/cards/<card>/scratches        {"scratches": "..."} -> save without running
    POST /api/cards/<card>/results          {"race_no", "finish", "win", "place", "show", "exotics"} -> results file
    POST /api/cards/<card>/ocr              {"race_no": n?, "force": bool} -> read screenshot(s) into the results file
    POST /api/cards/<card>/process          OCR any screenshot not yet on file, then back-test + wager evaluation -> results/<card>.backtest.md
    POST /api/upload  (multipart)           fields card, kind (pp|sheet|png), race_no (png), file
    POST /api/shutdown                      stop the server (used by `python ui.py stop`)
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

from brisnet_pp.parser import PARSER_VERSION                  # noqa: E402
from handicapper.engine import format_report, load_config   # noqa: E402
from handicapper.pipeline import run_card                     # noqa: E402
from handicapper.results import backtest, format_backtest, load_results   # noqa: E402
from handicapper.snapshot import latest_snapshot, list_snapshots, write_snapshot   # noqa: E402
from handicapper.wagering import evaluate_card, format_evaluation, format_units, rollup, units_table  # noqa: E402
from ocr_results import ocr_folder   # noqa: E402

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
CODE_GLOBS = ("ui/server.py", "ui/static/*", "handicapper/*.py", "brisnet_pp/*.py", "rules_config.json", "ocr_results.py")


def code_stamp() -> dict[str, float]:
    """Modification time of every file the running app is built from (relative path -> mtime)."""
    out = {}
    for g in CODE_GLOBS:
        for p in glob.glob(os.path.join(ROOT, *g.split("/"))):
            if os.path.isfile(p):
                out[os.path.relpath(p, ROOT).replace("\\", "/")] = os.path.getmtime(p)
    return out


STARTED_AT = datetime.now().isoformat(timespec="seconds")
CODE_AT_START = code_stamp()


def status() -> dict:
    """Is the code on disk newer than what this process loaded?  (After `git pull` the background app keeps
    running the old code until `python ui.py stop` / `start`.)"""
    now = code_stamp()
    changed = sorted(p for p, t in now.items() if p not in CODE_AT_START or t > CODE_AT_START[p] + 1)
    changed += sorted(p for p in CODE_AT_START if p not in now)
    return {"started": STARTED_AT, "parser_version": PARSER_VERSION, "code_changed": bool(changed), "changed_files": changed[:20]}
CARD_RE = re.compile(r"^[a-z0-9_-]{3,24}$", re.I)


def reparse_reason(pdf: str | None, card_json: str | None) -> str | None:
    """Why a cached card.json must be rebuilt from the PDF: no cache, the PDF is newer, or the parser changed."""
    if not pdf:
        return None
    if not card_json:
        return "no cached card"
    try:
        if os.path.getmtime(pdf) > os.path.getmtime(card_json) + 1:
            return "PDF is newer than the cached card"
        with open(card_json, encoding="utf-8") as fh:
            stamp = json.load(fh).get("parser_version")
    except (OSError, ValueError):
        return "cached card unreadable"
    if stamp != PARSER_VERSION:
        return f"parser changed ({stamp or 'unstamped'} -> {PARSER_VERSION})"
    return None


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
        charts = sorted(os.path.basename(p) for p in glob.glob(os.path.join(pngdir, "*.pdf")))
        return {"pp": pp if os.path.exists(pp) else None, "sheet": sheet,
                "card_json": self._opt(os.path.join(self.out, f"{card}.card.json")),
                "picks_json": self._opt(os.path.join(self.out, f"{card}.picks.json")),
                "results": self._opt(os.path.join(self.results, f"{card}.results.json")),
                "backtest_md": self._opt(os.path.join(self.results, f"{card}.backtest.md")),
                "pngs": pngs, "charts": charts}

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
    def run(self, card: str, scratches: str | None = None, reparse: bool = False, kind: str | None = None) -> dict:
        """kind: None = decide from the results on file (pre-race / post-results); "as-run" for the retrospective
        re-score.  Every run is also frozen as an append-only snapshot (handicapper/snapshot.py)."""
        f = self.files(card)
        source = f["pp"] or f["card_json"]
        if not source:
            raise FileNotFoundError(f"no PDF or card.json for {card}: put the PPs at data/pps/{card}.pdf")
        st = self.state(card)
        if scratches is not None:
            st["scratches"] = scratches
        with self.lock:
            # parse once and cache the raw card so the roster (with scratched horses) is always available;
            # re-read the PDF when asked, when it is newer than the cache, or when the parser has changed since
            why = reparse_reason(f["pp"], f["card_json"]) if f["pp"] else None
            if f["pp"] and (reparse or why):
                out = run_card(f["pp"], config_path=self.config, multirace=False)
                with open(os.path.join(self.out, f"{card}.card.json"), "w", encoding="utf-8") as fh:
                    json.dump(out["raw"], fh, indent=1, ensure_ascii=False)
                self.log(st, "Re-read PPs", why or "asked for")
            cj = os.path.join(self.out, f"{card}.card.json")
            out = run_card(cj, scratch=st.get("scratches") or None, sheet=f["sheet"], results=f["results"], config_path=self.config)
            result = out["result"]
            kind = kind or ("post-results" if result["run"]["results_known"] else "pre-race")
            result["run"]["kind"] = kind
            with open(os.path.join(self.out, f"{card}.picks.json"), "w", encoding="utf-8") as fh:
                json.dump(result, fh, indent=1, ensure_ascii=False, default=str)
            with open(os.path.join(self.out, f"{card}.picks.md"), "w", encoding="utf-8") as fh:
                fh.write(format_report(result, detail=2))
            snap = write_snapshot(self.out, card, result, kind)
        st.setdefault("runs", []).append({"at": datetime.now().isoformat(timespec="seconds"), "scratches": st.get("scratches", ""),
                                          "profile": result.get("track_profile"), "notes": out["notes"], "kind": kind,
                                          "snapshot": os.path.basename(snap)})
        self.log(st, "Run picks" if kind != "as-run" else "As-run re-score",
                 f"{len(result['races'])} races scored, profile {result.get('track_profile')}" +
                 (f", scratches: {st['scratches']}" if st.get("scratches") else "") + f"; snapshot {kind} {os.path.basename(snap)}")
        self.save_state(st)
        return self.payload(card)

    def payload(self, card: str) -> dict:
        f = self.files(card)
        st = self.state(card)
        roster, meta = [], {}
        if f["card_json"]:
            cj = json.load(open(f["card_json"], encoding="utf-8"))
            meta = {"track": cj.get("track"), "date": cj.get("date"), "track_code": cj.get("track_code")}
            if not meta["track_code"]:   # card.json written before the parser recorded it: take it from the horses
                from collections import Counter
                codes = Counter(h["records"].get("track_code") for r in cj["races"] for h in r["horses"] if h.get("records", {}).get("track_code"))
                meta["track_code"] = codes.most_common(1)[0][0] if codes else None
            for r in cj["races"]:
                roster.append({"race_no": r["race_no"], "class_text": r.get("class_text"), "distance_text": r.get("distance_text"),
                               "surface": r.get("surface"), "post_time": r.get("post_time"), "wagers": r.get("wagers"),
                               "horses": [{"pgm": h["pgm"], "post": h.get("post"), "name": h["name"], "ml_odds": h.get("ml_odds"),
                                           "run_style": h.get("run_style"), "speed_pts": h.get("speed_pts"), "entry_status": h.get("entry_status"),
                                           "jockey": h.get("jockey"), "trainer": h.get("trainer")} for h in r["horses"]]})
        picks = json.load(open(f["picks_json"], encoding="utf-8")) if f["picks_json"] else None
        if picks and not picks.get("track_code") and meta.get("track_code"):
            picks["track_code"] = meta["track_code"]
        results = load_results(f["results"]) if f["results"] else None
        bt = ev = pre = None
        if picks and results:
            wcfg = load_config(self.config)["wagering"]
            bt = backtest(picks, results)
            ev = evaluate_card(picks, results, wcfg)
            pre = self.pre_race(card, results, wcfg)
        snaps = [{k: v for k, v in s.items() if k != "path"} for s in list_snapshots(self.out, card)]
        return {"card": card, "meta": meta, "files": {k: (bool(v) if k not in ("pngs", "charts") else v) for k, v in f.items()},
                "state": st, "roster": roster, "picks": picks, "results": results, "backtest": bt, "evaluation": ev,
                "latest_kind": (picks or {}).get("run", {}).get("kind") or ("as-run" if picks and "as-run" in str(st.get("activity", [])[-1:]) else None),
                "pre_race": pre, "snapshots": snaps}

    def pre_race(self, card: str, results: dict, wcfg: dict) -> dict | None:
        """Back-test and wager evaluation of the newest pre-race snapshot: what the engine said before any result
        was on file, which no later run can change.  None when the card has no pre-race snapshot."""
        snap = latest_snapshot(self.out, card, "pre-race")
        if not snap:
            return None
        if not snap.get("track_code"):
            snap["track_code"] = self.payload_meta(card).get("track_code")
        return {"snapshot": snap["snapshot"], "run": snap.get("run"), "scratches": snap.get("scratches", ""),
                "backtest": backtest(snap, results), "evaluation": evaluate_card(snap, results, wcfg)}

    def payload_meta(self, card: str) -> dict:
        f = self.files(card)
        if not f["card_json"]:
            return {}
        cj = json.load(open(f["card_json"], encoding="utf-8"))
        return {"track": cj.get("track"), "date": cj.get("date"), "track_code": cj.get("track_code")}

    # ---------------------------------------------------------------- results
    def save_result(self, card: str, race: dict) -> dict:
        p = os.path.join(self.results, f"{card}.results.json")
        if os.path.exists(p):
            data = json.load(open(p, encoding="utf-8"))
        else:
            meta = self.payload(card)["meta"]
            data = {"track": meta.get("track"), "date": meta.get("date"), "_source": "entered in Race Day Desk", "races": []}
        rn = int(race["race_no"])
        # an edit corrects the submitted fields only; everything the chart gave (final odds, runners, condition,
        # provenance) stays, and the correction is recorded beside the original source
        existing = next((r for r in data["races"] if r["race_no"] == rn), None)
        entry = dict(existing) if existing else {"race_no": rn}
        fields = {"finish": [str(x).strip() for x in race.get("finish", []) if str(x).strip()],
                  "exotics": [{"type": e["type"].upper(), "base": float(e["base"]), "combo": e["combo"], "payout": float(e["payout"])}
                              for e in race.get("exotics", []) if e.get("combo") and e.get("payout") not in (None, "")]}
        if race.get("win") not in (None, ""):
            fields["win"] = float(race["win"])
        for k in ("place", "show"):
            if race.get(k):
                fields[k] = {str(a): float(b) for a, b in race[k].items() if b not in (None, "")}
        changed = sorted(k for k, v in fields.items() if existing is None or existing.get(k) != v)
        entry.update(fields)
        if existing is not None and changed:
            entry.setdefault("corrections", []).append({"at": datetime.now().isoformat(timespec="seconds"), "fields": changed,
                                                        "original_source": existing.get("source") or (existing.get("ocr") or {}).get("source") or "manual"})
        elif existing is None:
            entry["source"] = "manual"
        data["races"] = [r for r in data["races"] if r["race_no"] != rn] + [entry]
        data["races"].sort(key=lambda r: r["race_no"])
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        st = self.state(card)
        self.log(st, f"Result R{rn}", f"finish {'/'.join(entry['finish'])}" + (f", win ${entry['win']:.2f}" if "win" in entry else "")
                 + (f"; corrected {', '.join(changed)} (chart data kept)" if existing is not None and changed else ""))
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

    def chart_scratches(self, card: str) -> str:
        """Scratch list derived from the charts: every horse on the card that is not among a race's chart runners."""
        pl = self.payload(card)
        if not pl["results"] or not pl["roster"]:
            return ""
        out = []
        for r in pl["roster"]:
            ch = next((x for x in pl["results"]["races"] if x["race_no"] == r["race_no"]), None)
            if not ch or not ch.get("runners"):
                continue
            ran = {x["pgm"].upper() for x in ch["runners"]}
            out += [f"{r['race_no']}:{h['pgm']}" for h in r["horses"] if h["pgm"].upper() not in ran]
        return ", ".join(out)

    def process(self, card: str) -> dict:
        f = self.files(card)
        if f["pngs"] or f["charts"]:
            self.ocr(card)
        # re-score "as run": the charts say who actually ran, so the back-test compares against that field
        derived = self.chart_scratches(card)
        st = self.state(card)
        if derived:
            have = set(x.strip().upper() for x in (st.get("scratches") or "").split(",") if x.strip())
            want = set(x.strip().upper() for x in derived.split(","))
            if want - have:
                merged = ", ".join(sorted(have | want, key=lambda t: (int(t.split(":")[0]), t.split(":")[1])))
                self.log(st, "As-run re-score", f"charts show these did not run: {', '.join(sorted(want - have))}; re-running with scratches {merged}")
                self.save_state(st)
                self.run(card, merged, kind="as-run")
        pl = self.payload(card)
        if not (pl["picks"] and pl["results"]):
            raise ValueError("needs a run (picks) and at least one race result (a chart PDF, a screenshot r<N>.png or an entered result)")
        text = self.backtest_text(card, pl)
        with open(os.path.join(self.results, f"{card}.backtest.md"), "w", encoding="utf-8") as fh:
            fh.write(text)
        st = self.state(card)
        head = pl["pre_race"] or {"backtest": pl["backtest"], "evaluation": pl["evaluation"]}
        s, t = head["backtest"]["summary"], head["evaluation"]["totals"]
        basis = "pre-race snapshot" if pl["pre_race"] else "latest run (no pre-race snapshot on file)"
        self.log(st, "Process results", f"{basis}: top pick won {s['top_pick_wins']}/{s['races']}, winner in top 3 "
                 f"{s['winner_in_top3']}/{s['races']}; wagers {t['hits']}/{t['bets']} hit")
        self.save_state(st)
        pl["report"] = text
        return pl

    def backtest_text(self, card: str, pl: dict) -> str:
        """Two labelled sections: the pre-race prediction as bet (immutable snapshot) and the as-run re-score."""
        L = ["# " + card, ""]
        pre = pl.get("pre_race")
        if pre:
            L += [f"## Pre-race prediction, as bet  (snapshot {pre['snapshot']['file']}, {pre['snapshot']['at_utc']} UTC"
                  + (f", scratches {pre['scratches']}" if pre["scratches"] else "") + ")", "",
                  "These numbers cannot change: the snapshot was frozen before any result for this card was on file.", "",
                  format_backtest(pre["backtest"]), "", format_evaluation(pre["evaluation"]), ""]
        else:
            L += ["## No pre-race snapshot on file", "",
                  "This card was run before snapshots existed (or only after results were entered); the section below is "
                  "retrospective and must not be read as what the engine said before the races.", ""]
        kind = pl.get("latest_kind") or "latest"
        label = {"as-run": "As-run re-score  (retrospective: the field as the charts say it ran)",
                 "post-results": "Latest run  (made after some results were on file: retrospective for those races)",
                 "pre-race": "Latest run  (pre-race)"}.get(kind, "Latest run")
        L += [f"## {label}", "", format_backtest(pl["backtest"]), "", format_evaluation(pl["evaluation"])]
        return "\n".join(L)

    # ---------------------------------------------------------------- analysis
    def analysis(self) -> dict:
        full = load_config(self.config)
        cfg = full["wagering"]
        units = units_table(cfg) | {"PICK3": full["multirace"]["pick3"]["base"], "PICK4": full["multirace"]["pick4"]["base"]}
        evals, cards, rules = [], [], {}
        bench = {"races": 0, "engine_wins": 0, "brisnet_wins": 0, "brisnet_top3": 0, "best_bets": 0, "best_bet_wins": 0}
        for c in self.cards():
            f = self.files(c["card"])
            if not (f["picks_json"] and f["results"]):
                continue
            snap = latest_snapshot(self.out, c["card"], "pre-race")
            picks = snap or json.load(open(f["picks_json"], encoding="utf-8"))
            basis = "pre-race" if snap else "latest (retrospective)"
            res = load_results(f["results"])
            bt = backtest(picks, res)
            ev = evaluate_card(picks, res, cfg)
            ev["card_code"], ev["track_code"] = c["card"], picks.get("track_code") or c.get("track_code") or self.payload_meta(c["card"]).get("track_code")
            ev["basis"] = basis
            evals.append(ev)
            s = bt["summary"]
            cards.append({"card": c["card"], "track": ev["track_code"], "date": picks.get("date"), "races": s["races"], "basis": basis,
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
                rows.append(dict(x, card=ev["card_code"], track=ev["track_code"], date=ev.get("date"), basis=ev["basis"]))
        return {"rollup": rollup(evals) if evals else None, "cards": cards, "rules": rule_rows, "rows": rows, "benchmark": bench,
                "units": units, "units_text": format_units(units)}

    # ---------------------------------------------------------------- uploads
    def save_upload(self, card: str, kind: str, filename: str, data: bytes, race_no: int | None = None) -> dict:
        if not CARD_RE.match(card):
            raise ValueError("card code must be letters/digits, e.g. dmr1106y")
        if kind == "pp":
            path = os.path.join(self.pps, f"{card}.pdf")
        elif kind == "sheet":
            path = os.path.join(self.pps, f"{card[:-1]}q.pdf" if card.endswith("y") else f"{card}q.pdf")
        elif kind in ("png", "chart"):
            if not race_no:
                m = re.search(r"USA(\d{1,2})$", os.path.splitext(filename)[0], re.I) or re.search(r"r?(\d{1,2})", os.path.splitext(filename)[0])
                race_no = int(m.group(1)) if m else None
            if not race_no:
                raise ValueError(f"{kind} needs a race number (name it r3.{ 'png' if kind == 'png' else 'pdf'} or pass race_no)")
            os.makedirs(os.path.join(self.pngs, card), exist_ok=True)
            path = os.path.join(self.pngs, card, f"r{race_no}.{'png' if kind == 'png' else 'pdf'}")
        else:
            raise ValueError("kind must be pp, sheet, png or chart")
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

    def end_headers(self):   # the page and its script must never be served from the browser cache after a pull
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):   # quieter console: API calls and errors only
        line = fmt % args if args else fmt
        if "/api/" in line or "code 5" in line:
            sys.stderr.write("%s %s\n" % (time.strftime("%H:%M:%S"), line))

    def _json(self, obj, status=200):
        data = json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
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
            if u.path == "/api/status":
                return self._json(status())
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
            if u.path == "/api/shutdown":
                self._json({"ok": True, "stopping": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return None
            m = re.fullmatch(r"/api/cards/([^/]+)/(run|results|process|ocr)", u.path)
            if m:
                card, action = unquote(m.group(1)), m.group(2)
                if action == "run":
                    return self._json(self.desk.run(card, payload.get("scratches"), bool(payload.get("reparse"))))
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
