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
from handicapper.snapshot import latest_snapshot, list_snapshots, pre_race_by_race, write_snapshot   # noqa: E402


def load_env_file(path: str) -> dict:
    """KEY=VALUE lines from a .env file into os.environ (existing variables win).  Returns what was set."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ and v:
                os.environ[k] = v; out[k] = v
    return out
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

    def __init__(self, root: str = ROOT, weather: str | None = None, tote_provider=None):
        load_env_file(os.path.join(root, ".env"))
        # weather fetch: "auto" tries python-weather for tracks with a configured location; "off" records nothing
        self.weather = weather or os.environ.get("RACEDESK_WEATHER", "auto")
        # tote: an injected provider (tests: replay), else PuntersEdge unless RACEDESK_TOTE=off
        self.tote_provider = tote_provider
        self.tote_mode = "auto" if tote_provider is not None else os.environ.get("RACEDESK_TOTE", "auto")
        self._poller = None
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
                "changes": self._opt(os.path.join(self.pps, f"{card}.changes.html")) or self.day_changes_file(card),
                "timeform": self._opt(os.path.join(self.pps, f"{card}.tfus.pdf")) or self._opt(os.path.join(self.pps, f"{card}.tfus.txt")),
                "racing_dudes": self.day_file(card, "racingdudes_{date}.html"),
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
    def card_date(self, card: str) -> str | None:
        cj = os.path.join(self.out, f"{card}.card.json")      # read directly: files() calls this, payload_meta() calls files()
        if not os.path.exists(cj):
            return None
        try:
            with open(cj, encoding="utf-8") as fh:
                return json.load(fh).get("date")
        except (OSError, ValueError):
            return None

    def day_file(self, card: str, pattern: str) -> str | None:
        """A file saved once per race date for every track (data/pps/<pattern with the card's date>), if any."""
        date = self.card_date(card)
        return self._opt(os.path.join(self.pps, pattern.format(date=date))) if date else None

    def day_changes_file(self, card: str) -> str | None:
        """data/pps/latechanges_<date>.xml for this card's date (the day's Equibase file for every track), if any."""
        return self.day_file(card, "latechanges_{date}.xml")

    def load_changes(self, card: str, path: str) -> dict | None:
        """The changes for this card from a saved HTML page or the day's XML (matched by track code or name)."""
        from brisnet_pp.changes import load_changes_file
        meta = self.payload_meta(card)
        return load_changes_file(path, meta.get("track_code"), meta.get("track"), load_config(self.config))

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
        changes = None
        if f["changes"]:   # the Equibase changes page or the day's XML: its scratches join the list, its conditions go on the run
            from brisnet_pp.changes import merge_scratch_specs, scratch_spec, summary as changes_summary
            changes = self.load_changes(card, f["changes"])
        if changes:
            merged = merge_scratch_specs(st.get("scratches"), scratch_spec(changes))
            if merged != (st.get("scratches") or ""):
                self.log(st, "Changes page", f"scratches added from Equibase: {scratch_spec(changes) or 'none'}")
                st["scratches"] = merged
            st["changes"] = changes_summary(changes)
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
            wx = {"fetch": self.weather == "auto", "observations": list(st.get("weather") or [])}
            boards = {int(k): v for k, v in (self.tote_latest(card).get("races") or {}).items()}
            out = run_card(cj, scratch=st.get("scratches") or None, sheet=f["sheet"], results=f["results"], config_path=self.config,
                           changes=changes, timeform=f["timeform"], weather=wx, boards=boards, racing_dudes=f["racing_dudes"])
            result = out["result"]
            kind = kind or ("post-results" if result["run"]["results_known"] else "pre-race")
            result["run"]["kind"] = kind
            with open(os.path.join(self.out, f"{card}.picks.json"), "w", encoding="utf-8") as fh:
                json.dump(result, fh, indent=1, ensure_ascii=False, default=str)
            with open(os.path.join(self.out, f"{card}.picks.md"), "w", encoding="utf-8") as fh:
                fh.write(format_report(result, detail=2))
            snap = write_snapshot(self.out, card, result, kind)
        wxr = result["run"].get("weather") or {}
        if wxr.get("status") == "ok":    # fetched observations join the card's record (append-only, with provenance)
            have = {(o.get("observed_at_utc"), o.get("race_no"), o.get("provenance")) for o in st.get("weather") or []}
            st.setdefault("weather", []).extend(o for o in wxr.get("observations", []) if (o.get("observed_at_utc"), o.get("race_no"), o.get("provenance")) not in have)
        tm = result["run"].get("timing") or {}
        st.setdefault("runs", []).append({"at": datetime.now().isoformat(timespec="seconds"), "scratches": st.get("scratches", ""),
                                          "profile": result.get("track_profile"), "notes": out["notes"], "kind": kind,
                                          "snapshot": os.path.basename(snap),
                                          "timing": f"{tm.get('before', 0)} before / {tm.get('after', 0)} after / {tm.get('unknown', 0)} unknown"})
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
                               "inputs": r.get("inputs"), "surface_switch": r.get("surface_switch"), "timeform": r.get("timeform"), "racing_dudes": r.get("racing_dudes"),
                               "horses": [{"pgm": h["pgm"], "post": h.get("post"), "name": h["name"], "ml_odds": h.get("ml_odds"),
                                           "run_style": h.get("run_style"), "speed_pts": h.get("speed_pts"), "entry_status": h.get("entry_status"),
                                           "jockey": h.get("jockey"), "trainer": h.get("trainer")} for h in r["horses"]]})
        picks = json.load(open(f["picks_json"], encoding="utf-8")) if f["picks_json"] else None
        if picks and not picks.get("track_code") and meta.get("track_code"):
            picks["track_code"] = meta["track_code"]
        if picks:   # the latest run's inputs, surface switch and Timeform reading belong to the race, not the raw parse
            pk = {r["race_no"]: r for r in picks.get("races", [])}
            for r in roster:
                for k in ("inputs", "surface_switch", "timeform", "racing_dudes"):
                    if r["race_no"] in pk and k in pk[r["race_no"]]:
                        r[k] = pk[r["race_no"]][k]
        results = load_results(f["results"]) if f["results"] else None
        picks = self.apply_decisions(picks, st.get("decisions"))
        bt = ev = pre = None
        results_error = None
        if picks and results:
            wcfg = load_config(self.config)["wagering"]
            try:
                bt = backtest(picks, results)
                ev = evaluate_card(picks, results, wcfg)
                pre = self.pre_race(card, results, wcfg)
            except ValueError as e:          # results from another card: refuse to score, say why
                results_error = str(e)
        snaps = [{k: v for k, v in s.items() if k != "path"} for s in list_snapshots(self.out, card)]
        return {"card": card, "meta": meta, "files": {k: (bool(v) if k not in ("pngs", "charts") else v) for k, v in f.items()},
                "state": st, "roster": roster, "picks": picks, "results": results, "backtest": bt, "evaluation": ev,
                "results_error": results_error,
                "latest_kind": (picks or {}).get("run", {}).get("kind") or ("as-run" if picks and "as-run" in str(st.get("activity", [])[-1:]) else None),
                "pre_race": pre, "snapshots": snaps,
                "tote": self.tote_latest(card, meta) if meta.get("track_code") else {"status": None, "races": {}},
                "decisions": st.get("decisions", {}),
                "last_run_scratches": (st.get("runs") or [{}])[-1].get("scratches", "") if st.get("runs") else None}

    def pre_race(self, card: str, results: dict, wcfg: dict) -> dict | None:
        """Back-test and wager evaluation of the newest pre-race snapshot: what the engine said before any result
        was on file, which no later run can change.  None when the card has no pre-race snapshot."""
        snap = self.clock_snapshot(card, results)
        if not snap:
            return None
        snap = self.apply_decisions(snap, self.state(card).get("decisions"))
        return {"snapshot": snap["snapshot"], "run": snap.get("run"), "scratches": snap.get("scratches", ""), "timing": snap.get("timing"),
                "backtest": backtest(snap, results), "evaluation": evaluate_card(snap, results, wcfg)}

    def clock_snapshot(self, card: str, results: dict | None) -> dict | None:
        """The pre-race prediction per race, chosen by each race's cutoff (handicapper/snapshot.pre_race_by_race)."""
        full = load_config(self.config)
        meta = self.payload_meta(card)
        code = meta.get("track_code")
        tz = ((full.get("tracks") or {}).get(code or "") or {}).get("timezone")
        snap = pre_race_by_race(self.out, card, results, tz, full.get("timing", {}).get("cutoff_margin_minutes", 2))
        if snap and not snap.get("track_code"):
            snap["track_code"] = code
        return snap

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
            tm = pre.get("timing") or {}
            L += [f"## Pre-race prediction, as bet  (per race the newest run made without that race's result; "
                  f"clock: {tm.get('before', 0)} before cutoff, {tm.get('after', 0)} after, {tm.get('unknown', 0)} unknown)", "",
                  "A run made after the race used only the PPs and the scratches, which are public before post, so it is a "
                  "pre-race prediction; the clock column is a record, not a filter.", "",
                  "Race: run used (UTC), clock status, cutoff basis (off = chart's actual off time, scheduled = PP post time):", ""]
            L += [f"- R{rn}: {v['file']} at {v['at_utc']} ({v['status']}, {v['basis']})" + (f", scratches {v['scratches']}" if v.get("scratches") else "") for rn, v in sorted(tm.get("per_race", {}).items(), key=lambda kv: int(kv[0]))]
            if tm.get("excluded"):
                L.append(f"- excluded (every run already had the result on file): R{', R'.join(str(x) for x in tm['excluded'])}")
            L += ["", "These numbers cannot change: a later run never rewrites an earlier record.", "",
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
        bench = {"races": 0, "engine_wins": 0, "brisnet_wins": 0, "brisnet_top3": 0, "best_bets": 0, "best_bet_wins": 0,
                 "rd_races": 0, "rd_wins": 0, "rd_top4": 0, "rd_engine_wins": 0, "rd_likely": 0, "rd_likely_wins": 0}
        refused = []
        for c in self.cards():
            f = self.files(c["card"])
            if not (f["picks_json"] and f["results"]):
                continue
            res = load_results(f["results"])
            snap = self.clock_snapshot(c["card"], res)
            picks = snap or json.load(open(f["picks_json"], encoding="utf-8"))
            basis = ("pre-race (" + snap["timing"]["label"] + ")") if snap else "latest (retrospective)"
            try:
                bt = backtest(picks, res)
                ev = evaluate_card(picks, res, cfg)
            except ValueError as e:              # results that are not this card's: listed, never scored
                refused.append({"card": c["card"], "reason": str(e)})
                continue
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
            if s.get("rd_races"):
                bench["rd_races"] += s["rd_races"]; bench["rd_wins"] += s["rd_pick_wins"]; bench["rd_top4"] += s["rd_top4"]
                bench["rd_engine_wins"] += s["rd_engine_wins"]; bench["rd_likely"] += s["rd_likely_winner"]; bench["rd_likely_wins"] += s["rd_likely_winner_wins"]
        rule_rows = sorted(rules.values(), key=lambda d: (-d["fired"], d["rule"]))
        for d in rule_rows:
            d["win_pct"] = round(100.0 * d["won"] / d["fired"], 1) if d["fired"] else 0
            d["itm_pct"] = round(100.0 * d["itm"] / d["fired"], 1) if d["fired"] else 0
        rows = []
        for ev in evals:
            for x in ev["rows"]:
                rows.append(dict(x, card=ev["card_code"], track=ev["track_code"], date=ev.get("date"), basis=ev["basis"]))
        try:
            from handicapper.sources import compare as sources_compare
            sources = sources_compare(self.root, full)
        except Exception as e:   # never takes the analysis screen down
            traceback.print_exc()
            sources = {"error": str(e)}
        try:
            from handicapper.bestbets import record as bb_record
            best = bb_record(self.root, full)
        except Exception as e:   # never takes the analysis screen down
            traceback.print_exc()
            best = {"error": str(e)}
        try:
            from handicapper.angles import angle_report
            angles = angle_report(self.root, full)
        except Exception as e:   # never takes the analysis screen down
            traceback.print_exc()
            angles = {"error": str(e)}
        try:
            from handicapper.evaluation import evaluate
            from handicapper.deferred import statuses
            evaluation = evaluate(self.root, full)
            evaluation["deferred"] = statuses(evaluation["data_watch"])
        except Exception as e:   # the evaluation never takes the analysis screen down
            traceback.print_exc()
            evaluation = {"error": str(e)}
        return {"rollup": rollup(evals) if evals else None, "cards": cards, "rules": rule_rows, "rows": rows, "benchmark": bench,
                "units": units, "units_text": format_units(units), "evaluation": evaluation, "angles": angles, "best_bets": best, "sources": sources, "refused": refused}

    # ---------------------------------------------------------------- uploads
    @staticmethod
    def timeform_identity(data: bytes) -> dict:
        """Track name and date read from a TimeformUS PP PDF (parsed in a temp file; the file is not kept)."""
        import tempfile
        from timeform_pp.reader import identity, parse_lines, parse_pdf
        if not data.startswith(b"%PDF"):          # a saved text layer
            return identity(parse_lines(data.decode("utf-8", errors="replace").splitlines()))
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(data)
            tmp = fh.name
        try:
            return identity(parse_pdf(tmp))
        finally:
            os.remove(tmp)

    def card_identity(self, card: str) -> dict | None:
        """What this card is (track, track code, date) from its picks, its parsed card or its results."""
        f = self.files(card)
        for p in (f["picks_json"], f["card_json"]):
            if p:
                with open(p, encoding="utf-8") as fh:
                    d = json.load(fh)
                return {"track": d.get("track"), "track_code": d.get("track_code"), "date": d.get("date")}
        if f["results"]:
            d = load_results(f["results"])
            return {"track": d.get("track"), "track_code": None, "date": d.get("date")}
        return None

    def guard_timeform(self, card: str, data: bytes) -> None:
        """The Timeform file must be for this card's track and day (same guard as the PP; track by canonical code)."""
        have = self.card_identity(card)
        if not have or not (have.get("date") or have.get("track")):
            return
        new = self.timeform_identity(data)
        from handicapper.identity import canonical_track
        cfg = load_config(self.config)
        problems = []
        if have.get("date") and new.get("date") and str(have["date"]) != str(new["date"]):
            problems.append(f"date {new['date']} vs this card's {have['date']}")
        hc = (have.get("track_code") or canonical_track(have.get("track"), cfg) or "").upper()
        nc = (canonical_track(new.get("track"), cfg) or "").upper()
        if hc and nc and hc != nc:
            problems.append(f"track {new['track']!r} ({nc}) vs this card's {have['track']!r} ({hc})")
        elif not nc and have.get("track") and new.get("track") and have["track"].strip().lower() != new["track"].strip().lower():
            problems.append(f"track {new['track']!r} vs this card's {have['track']!r}")
        if problems:
            raise ValueError(f"refused: this Timeform file is not {card}'s ({'; '.join(problems)}).")

    def save_weather(self, card: str, text: str) -> dict:
        """Owner-typed weather for the selected card: a manual observation with provenance, appended, never replacing
        a fetched one.  Rules do not read it."""
        from handicapper.weather import parse_manual
        obs = parse_manual(text)
        st = self.state(card)
        st.setdefault("weather", []).append(obs)
        self.log(st, "Weather typed", (text or "").strip()[:120])
        self.save_state(st)
        return {"ok": True, "observation": obs, "count": len(st["weather"])}

    # ---------------------------------------------------------------- tote (Phase C)
    def raw_config(self) -> dict:
        with open(self.config, encoding="utf-8") as fh:
            return json.load(fh)

    def tote_poller(self):
        """The poller, built once: PuntersEdge (key from PUNTERSEDGE_API_KEY or data/private/puntersedge.key) or the
        injected provider.  None when the tote is off."""
        if self._poller is None and self.tote_mode != "off":
            from carovex.tote import PuntersEdgeProvider, TotePoller
            cfg = self.raw_config()
            prov = self.tote_provider or PuntersEdgeProvider(root=self.root, timeout=float((cfg.get("tote") or {}).get("timeout_seconds", 15)),
                                                             max_retries=int((cfg.get("tote") or {}).get("max_retries", 3)))
            self._poller = TotePoller(self.root, prov, cfg)
        return self._poller

    def tote_refresh(self, card: str, race_no: int | None = None) -> dict:
        """One board read for this card's track and day (2 credits); changed boards are stored as observations.
        Returns {"status", "races": {race_no: board}, "next_in"}; a feed failure is a status, never an error."""
        meta = self.payload_meta(card)
        poller = self.tote_poller()
        if poller is None:
            return {"status": {"feed": "off", "reason": "tote is off (RACEDESK_TOTE=off)", "decisions_enabled": False}, "races": {}, "next_in": None}
        if not meta.get("track_code") or not meta.get("date"):
            return {"status": {"feed": "error", "reason": "the card has no track code or date yet (run picks first)", "decisions_enabled": False}, "races": {}, "next_in": None}
        res = poller.poll(meta["track_code"], str(meta["date"]), races=[race_no] if race_no else None)
        if res["ok"]:
            from carovex.ledger import race_id
            for rn, b in list(res["races"].items()):
                if b.get("final") and (poller.capture.latest(race_id(meta["track_code"], str(meta["date"]), int(rn))) or {}).get("kind") != "final":
                    fin = poller.final(meta["track_code"], str(meta["date"]), int(rn), b.get("source_race_id"))
                    if fin["ok"] and int(rn) in fin["races"]:
                        res["races"][rn] = fin["races"][int(rn)]
        st = self.state(card)
        st["tote"] = {"status": res["status"], "last_refresh": datetime.now().isoformat(timespec="seconds"),
                      "races": {str(rn): {"observation_id": b.get("observation_id"), "status": b.get("status"), "read_at": b.get("provider_read_at_utc")}
                                for rn, b in res["races"].items()} | (st.get("tote") or {}).get("races", {})}
        self.log(st, "Tote refresh", f"{res['status'].get('feed')}: {len(res['races'])} races" + (f"; {res['status'].get('reason')}" if res["status"].get("reason") else ""))
        self.save_state(st)
        return {"status": res["status"], "races": {str(k): v for k, v in res["races"].items()}, "next_in": res["next_in"]}

    def tote_latest(self, card: str, meta: dict | None = None) -> dict:
        """Latest stored board per race (from the ledger), with freshness against the clock now."""
        meta = meta or self.payload_meta(card)
        out = {"status": (self.state(card).get("tote") or {}).get("status"), "races": {}}
        if not meta.get("track_code") or not os.path.exists(os.path.join(self.root, "data", "private", "carovex.db")):
            return out
        from carovex.ledger import connect, race_id
        from carovex.tote import DEFAULT_TOTE, Capture, freshness, utc_now
        cap = Capture(self.root, con=connect(self.root))
        stale = int((self.raw_config().get("tote") or {}).get("stale_seconds", DEFAULT_TOTE["stale_seconds"]))
        f = self.files(card)
        races = [r["race_no"] for r in json.load(open(f["card_json"], encoding="utf-8"))["races"]] if f["card_json"] else []
        for rn in races:
            b = cap.latest(race_id(meta["track_code"], str(meta["date"]), rn))
            if b:
                b["freshness"] = freshness(b, utc_now(), stale)
                b.pop("history", None); b.pop("exotics", None)
                out["races"][str(rn)] = b
        return out

    def tote_history(self, card: str, race_no: int) -> dict:
        """Every stored board for one race, oldest first, reduced to what the Market view plots."""
        meta = self.payload_meta(card)
        if not meta.get("track_code") or not os.path.exists(os.path.join(self.root, "data", "private", "carovex.db")):
            return {"race_no": race_no, "reads": []}
        from carovex.ledger import connect, race_id
        from carovex.tote import Capture
        hist = Capture(self.root, con=connect(self.root)).history(race_id(meta["track_code"], str(meta["date"]), race_no))
        reads = [{"observation_id": b.get("observation_id"), "kind": b.get("kind"), "read_at": b.get("provider_read_at_utc"), "received_at": b.get("received_at_utc"),
                  "status": b.get("status"), "final": b.get("final"), "win_pool_total": b.get("win_pool_total"),
                  "odds": {k: v.get("odds_to_1") for k, v in (b.get("interests") or {}).items()},
                  "allocation": b.get("allocation"), "scratched": b.get("scratched"), "flags": b.get("flags")} for b in hist]
        return {"race_no": race_no, "reads": reads}

    def best_bets(self, date: str | None = None) -> dict:
        """Today's best bets (handicapper/bestbets.py: the engine's win bets ranked by expected value at the morning
        line, top two per card) from each card's latest run, with the record of the same rule on every card on file."""
        from handicapper.bestbets import PER_CARD, record, select, summary_line
        rows = []
        for c in self.cards():
            f = self.files(c["card"])
            if not f["picks_json"]:
                continue
            with open(f["picks_json"], encoding="utf-8") as fh:
                picks = json.load(fh)
            if date and str(picks.get("date")) != str(date):
                continue
            rows += [dict(b, card=c["card"], track=picks.get("track_code"), date=picks.get("date")) for b in select(picks)]
        rec = record(self.root, load_config(self.config))
        return {"date": date, "bets": rows, "per_card": PER_CARD,
                "label": "Best bets of the day: the engine's win bets ranked by expected value at the morning line. A labelled view, not a validated edge. "
                         + summary_line(rec),
                "record": {k: rec[k] for k in ("all", "at_price", "passed_winners", "cards", "first_date", "last_date")}}

    def mark_decision(self, card: str, decision_id: str, status: str, note: str = "") -> dict:
        """The owner's word on one suggested wager: paper (intends) or accepted (placed elsewhere and says so), with
        the current quote snapshot attached.  The only path to price_basis observed."""
        from carovex.tote import mark_decision, quote_for
        f = self.files(card)
        if not f["picks_json"]:
            raise ValueError("run picks first")
        picks = json.load(open(f["picks_json"], encoding="utf-8"))
        wager = race = None
        for r in picks["races"]:
            for w in r.get("wagers", []):
                if (w.get("decision") or {}).get("id") == decision_id:
                    wager, race = w, r
        if wager is None:
            raise ValueError(f"no wager with decision id {decision_id} in the current picks")
        latest = self.tote_latest(card)["races"].get(str(race["race_no"]))
        quote = quote_for(latest, wager["legs"])
        rec = mark_decision(self.root, card, decision_id, status, quote, note)
        rec["race_no"], rec["type"], rec["label"] = race["race_no"], wager["type"], wager.get("label")
        st = self.state(card)
        st.setdefault("decisions", {})[decision_id] = rec
        self.log(st, "Decision", f"R{race['race_no']} {wager.get('label')}: {status}" + (f" at {quote['odds_text']}" if quote and quote.get("odds_text") else ""))
        self.save_state(st)
        return rec

    @staticmethod
    def apply_decisions(picks: dict | None, decisions: dict | None) -> dict | None:
        """Overlay the owner's marks on the wagers of a picks document before evaluation (the files stay as written)."""
        if not picks or not decisions:
            return picks
        for r in picks.get("races", []):
            for w in r.get("wagers", []):
                d = w.get("decision") or {}
                rec = decisions.get(d.get("id"))
                if rec:
                    w["decision"] = dict(d, status=rec["status"], quote=rec.get("quote"), price_basis=rec.get("price_basis", d.get("price_basis")),
                                         marked_at_utc=rec.get("at_utc"))
        return picks

    def pp_identity(data: bytes) -> dict:
        """Track name, track code and date read from a PP PDF (parsed in a temp file; the file is not kept)."""
        import tempfile
        from brisnet_pp.parser import parse_pdf
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(data)
            tmp = fh.name
        try:
            c = parse_pdf(tmp)
            return {"track": c.get("track"), "track_code": c.get("track_code"), "date": c.get("date")}
        finally:
            os.remove(tmp)

    def guard_pp(self, card: str, data: bytes) -> None:
        """A card that already has picks, snapshots or results is a record: a PP for another track or day must
        not replace its PPs (dropping the wrong file on the open card is an easy mistake).  Raises ValueError."""
        f = self.files(card)
        have = None
        for p in (f["picks_json"], f["card_json"]):
            if p:
                with open(p, encoding="utf-8") as fh:
                    d = json.load(fh)
                have = {"track": d.get("track"), "track_code": d.get("track_code"), "date": d.get("date")}
                break
        if have is None and f["results"]:
            d = load_results(f["results"]); have = {"track": d.get("track"), "track_code": None, "date": d.get("date")}
        if not have or not (have.get("date") or have.get("track")):
            return
        new = self.pp_identity(data)
        problems = []
        if have.get("date") and new.get("date") and str(have["date"]) != str(new["date"]):
            problems.append(f"date {new['date']} vs this card's {have['date']}")
        if have.get("track") and new.get("track") and have["track"].strip().lower() != new["track"].strip().lower():
            problems.append(f"track {new['track']!r} vs this card's {have['track']!r}")
        if problems:
            raise ValueError(f"refused: this PP is not {card}'s ({'; '.join(problems)}). Type the new card code in "
                             f"'New card code' first, then drop the file again.")

    def save_upload(self, card: str, kind: str, filename: str, data: bytes, race_no: int | None = None) -> dict:
        if not CARD_RE.match(card):
            raise ValueError("card code must be letters/digits, e.g. dmr1106y")
        if kind == "pp":
            path = os.path.join(self.pps, f"{card}.pdf")
            self.guard_pp(card, data)        # never overwrite a card's PPs with another day's or track's
        elif kind == "sheet":
            path = os.path.join(self.pps, f"{card[:-1]}q.pdf" if card.endswith("y") else f"{card}q.pdf")
        elif kind == "changes":
            from brisnet_pp.changes import is_late_changes_xml, parse_late_changes_xml
            if is_late_changes_xml(data):      # the day's file for every track: saved once, applied to every card of that date
                doc = parse_late_changes_xml(data)
                date = doc.get("race_date") or datetime.now().strftime("%Y-%m-%d")
                date = re.sub(r"[^0-9A-Za-z-]", "-", str(date))      # never a path separator in the file name
                path = os.path.join(self.pps, f"latechanges_{date}.xml")
                with open(path, "wb") as fh:
                    fh.write(data)
                applied = []
                for c in self.cards():
                    meta = self.payload_meta(c["card"])
                    if str(meta.get("date")) != str(date):
                        continue
                    chg = self.load_changes(c["card"], path)
                    if not chg:
                        continue
                    from brisnet_pp.changes import scratch_spec, summary as changes_summary
                    st = self.state(c["card"]); st["changes"] = changes_summary(chg)
                    self.log(st, "Load changes", f"{os.path.basename(path)} ({chg.get('track')}): scratches {scratch_spec(chg) or 'none'}")
                    self.save_state(st); applied.append({"card": c["card"], "track": chg.get("track"), "scratches": scratch_spec(chg)})
                return {"saved": os.path.relpath(path, self.root), "race_date": date, "tracks": [t["track_name"] for t in doc["tracks"]], "applied": applied}
            path = os.path.join(self.pps, f"{card}.changes.html")
        elif kind == "racingdudes":
            from racing_dudes.reader import is_racing_dudes, parse_page as parse_rd, track_day
            if not is_racing_dudes(data):
                raise ValueError("refused: this is not a saved Racing Dudes picks page")
            doc = parse_rd(data, filename)
            dates = sorted({d for t in doc["tracks"] for d in t["days"]})
            if not dates:
                raise ValueError("no picks found in this page (save it as 'Webpage, HTML only' after the races are expanded)")
            saved = []
            for d in dates:                    # one copy per race date on the page: a later page for that date replaces it
                p = os.path.join(self.pps, f"racingdudes_{d}.html")
                with open(p, "wb") as fh:
                    fh.write(data)
                saved.append(os.path.relpath(p, self.root))
            cfg = load_config(self.config)
            applied = []
            for c in self.cards():
                meta = self.payload_meta(c["card"])
                if str(meta.get("date")) not in dates:
                    continue
                races = track_day(doc, str(meta.get("date")), meta.get("track_code"), meta.get("track"), cfg)
                if races:
                    st = self.state(c["card"]); self.log(st, "Load Racing Dudes", f"{len(races)} races for {meta.get('track')} {meta.get('date')}"); self.save_state(st)
                    applied.append({"card": c["card"], "track": meta.get("track"), "races": len(races)})
            return {"saved": saved[0], "files": saved, "race_dates": dates, "tracks": [t["name"] for t in doc["tracks"]], "applied": applied}
        elif kind == "timeform":
            path = os.path.join(self.pps, f"{card}.tfus.{'pdf' if data.startswith(b'%PDF') else 'txt'}")
            self.guard_timeform(card, data)  # same identity guard as the PP: another track's or day's file is refused
        elif kind in ("png", "chart"):
            fm = re.match(r"^(\d{4})(\d{2})(\d{2})([A-Z]{2,4})USA(\d{1,2})$", os.path.splitext(filename)[0], re.I)
            if fm and kind == "chart":        # Equibase's own file name says which day and track the chart is
                meta = self.payload_meta(card)
                fdate, fcode = f"{fm.group(1)}-{fm.group(2)}-{fm.group(3)}", fm.group(4).upper()
                problems = []
                if meta.get("date") and str(meta["date"]) != fdate:
                    problems.append(f"chart is dated {fdate}, card {card} is {meta['date']}")
                if meta.get("track_code") and fcode != str(meta["track_code"]).upper():
                    problems.append(f"chart is for {fcode}, card {card} is {meta['track_code']}")
                if problems:
                    raise ValueError(f"refused {filename}: " + "; ".join(problems))
            if not race_no:
                m = re.search(r"USA(\d{1,2})$", os.path.splitext(filename)[0], re.I) or re.search(r"r?(\d{1,2})", os.path.splitext(filename)[0])
                race_no = int(m.group(1)) if m else None
            if not race_no:
                raise ValueError(f"{kind} needs a race number (name it r3.{ 'png' if kind == 'png' else 'pdf'} or pass race_no)")
            os.makedirs(os.path.join(self.pngs, card), exist_ok=True)
            path = os.path.join(self.pngs, card, f"r{race_no}.{'png' if kind == 'png' else 'pdf'}")
        else:
            raise ValueError("kind must be pp, sheet, changes, timeform, racingdudes, png or chart")
        with open(path, "wb") as fh:
            fh.write(data)
        if kind == "changes":
            from brisnet_pp.changes import parse_changes, scratch_spec, summary as changes_summary
            chg = parse_changes(data.decode("utf-8", errors="replace"))
            st = self.state(card); st["changes"] = changes_summary(chg); self.save_state(st)
            return {"saved": os.path.relpath(path, self.root), "scratches": scratch_spec(chg), "conditions": chg.get("conditions"),
                    "updated": chg.get("updated"), "track": chg.get("track")}
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
            if u.path == "/api/best-bets":
                q = dict(x.split("=", 1) for x in u.query.split("&") if "=" in x)
                return self._json(self.desk.best_bets(unquote(q.get("date", "")) or None))
            m = re.fullmatch(r"/api/cards/([^/]+)/tote/history", u.path)
            if m:
                q = dict(x.split("=", 1) for x in u.query.split("&") if "=" in x)
                return self._json(self.desk.tote_history(unquote(m.group(1)), int(q.get("race_no", "0") or 0)))
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
                extra = [o for o in out if o.get("applied") is not None]
                return self._json({"saved": [o["saved"] for o in out], "applied": [a for o in extra for a in o["applied"]], "tracks": [t for o in extra for t in o.get("tracks", [])],
                                   "kind": fields.get("kind")})
            body = self._body()
            payload = json.loads(body) if body else {}
            if u.path == "/api/shutdown":
                self._json({"ok": True, "stopping": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return None
            m = re.fullmatch(r"/api/cards/([^/]+)/(run|results|process|ocr|weather|tote|decisions)", u.path)
            if m:
                card, action = unquote(m.group(1)), m.group(2)
                if action == "tote":
                    rn = payload.get("race_no")
                    return self._json(self.desk.tote_refresh(card, int(rn) if rn else None))
                if action == "decisions":
                    return self._json(self.desk.mark_decision(card, payload.get("decision_id", ""), payload.get("status", ""), payload.get("note", "")))
                if action == "weather":
                    return self._json(self.desk.save_weather(card, payload.get("text", "")))
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
