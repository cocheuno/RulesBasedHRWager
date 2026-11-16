"""
The decision ledger: SQLite at data/private/carovex.db (git-ignored), versioned migrations, append-only.

Legacy JSON (picks, snapshots, results) stays the source of truth for what the engine said and what happened;
the ledger indexes it with the times things became known, so one query answers "what was known at time T":

    python -m carovex.ledger import <repo root> [card ...]      index every snapshot, decision and result
    python -m carovex.ledger as-of <repo root> <card> <race> <UTC time>

Tables: race, betting_interest, source_observation, forecast, decision, execution, settlement.  Rows are never
updated; a correction is a new row.  Results imported from a file get received_at = the import time (the ledger
cannot know when a chart was read before it existed); from Phase A on the Desk imports at process time.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

SCHEMA_VERSION = 1
MIGRATIONS = {
    1: """
    CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL, applied_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS race (
        race_id TEXT PRIMARY KEY,            -- <track_code>|<date>|<race_no>
        card TEXT NOT NULL, track_code TEXT, race_date TEXT NOT NULL, race_no INTEGER NOT NULL,
        surface TEXT, distance_text TEXT, post_at_utc TEXT, off_at_utc TEXT, source TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS betting_interest (
        interest_id TEXT PRIMARY KEY,        -- <race_id>|<pgm>
        race_id TEXT NOT NULL REFERENCES race(race_id), pgm TEXT NOT NULL, horse_name TEXT, coupled INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'entered', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS source_observation (
        observation_id TEXT PRIMARY KEY, provider TEXT NOT NULL, document TEXT, content_hash TEXT,
        event_at_utc TEXT, provider_read_at_utc TEXT, received_at_utc TEXT NOT NULL, available_at_utc TEXT NOT NULL,
        race_id TEXT, payload TEXT, created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS ix_obs_race ON source_observation(race_id, available_at_utc);
    CREATE TABLE IF NOT EXISTS forecast (
        forecast_id TEXT PRIMARY KEY, race_id TEXT NOT NULL REFERENCES race(race_id), snapshot_file TEXT NOT NULL,
        model TEXT NOT NULL, config_hash TEXT, parser_version TEXT, code_version TEXT, predicted_at_utc TEXT NOT NULL,
        cutoff_status TEXT, vector TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS ix_forecast_race ON forecast(race_id, predicted_at_utc);
    CREATE TABLE IF NOT EXISTS decision (
        decision_id TEXT PRIMARY KEY, race_id TEXT NOT NULL REFERENCES race(race_id), forecast_id TEXT REFERENCES forecast(forecast_id),
        snapshot_file TEXT NOT NULL, decided_at_utc TEXT NOT NULL, cutoff_status TEXT, wager_type TEXT NOT NULL, legs TEXT NOT NULL,
        label TEXT, unit REAL, min_odds TEXT, price_basis TEXT NOT NULL, status TEXT NOT NULL, config_hash TEXT, created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS ix_decision_race ON decision(race_id, decided_at_utc);
    CREATE TABLE IF NOT EXISTS execution (
        execution_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL REFERENCES decision(decision_id),
        status TEXT NOT NULL DEFAULT 'not_submitted', quote_observation_id TEXT, verified_by TEXT, recorded_at_utc TEXT NOT NULL,
        note TEXT, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS settlement (
        settlement_id TEXT PRIMARY KEY, race_id TEXT NOT NULL REFERENCES race(race_id), source TEXT NOT NULL, version INTEGER NOT NULL,
        finish TEXT NOT NULL, payouts TEXT NOT NULL, final_odds TEXT, off_at_utc TEXT, received_at_utc TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS ix_settlement_race ON settlement(race_id, received_at_utc);
    """,
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def db_path(root: str) -> str:
    return os.path.join(root, "data", "private", "carovex.db")


def connect(root: str) -> sqlite3.Connection:
    """Open (creating and migrating as needed) the ledger under <root>/data/private."""
    p = db_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    con = sqlite3.connect(p, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con)
    return con


def migrate(con: sqlite3.Connection) -> int:
    con.executescript(MIGRATIONS[1].split("CREATE TABLE IF NOT EXISTS race")[0])   # schema_version first
    row = con.execute("SELECT MAX(version) FROM schema_version").fetchone()
    have = row[0] or 0
    for v in range(have + 1, SCHEMA_VERSION + 1):
        con.executescript(MIGRATIONS[v])          # executescript runs in its own transaction
        con.execute("INSERT INTO schema_version(version, applied_at) VALUES (?, ?)", (v, now_utc()))
    return SCHEMA_VERSION


def race_id(track_code: str | None, date: str | None, race_no: int) -> str:
    return f"{track_code or '?'}|{date or '?'}|{race_no}"


def import_card(root: str, card: str, con: sqlite3.Connection | None = None) -> dict:
    """Index every snapshot of a card (races, interests, forecasts, decisions) and its results file as settlements.
    Idempotent: rows keyed by content never duplicate; re-importing adds nothing."""
    from handicapper.snapshot import list_snapshots
    con = con or connect(root)
    out = {"snapshots": 0, "forecasts": 0, "decisions": 0, "settlements": 0, "observations": 0}
    out_dir = os.path.join(root, "data", "out")
    ts = now_utc()
    for meta in list_snapshots(out_dir, card):
        with open(meta["path"], encoding="utf-8") as fh:
            s = json.load(fh)
        run = s.get("run") or {}
        at = run.get("at_utc") or (s.get("snapshot") or {}).get("at_utc")
        cut = run.get("cutoffs") or {}
        out["snapshots"] += 1
        con.execute("BEGIN")
        for r in s.get("races", []):
            rid = race_id(s.get("track_code"), s.get("date"), r["race_no"])
            c = cut.get(str(r["race_no"])) or {}
            con.execute("INSERT OR IGNORE INTO race VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (rid, card, s.get("track_code"), s.get("date"), r["race_no"], r.get("surface"), r.get("distance_text"),
                         c.get("post_at_utc"), c.get("off_at_utc"), "snapshot:" + meta["file"], ts))
            for sh in r.get("sheets", []):
                con.execute("INSERT OR IGNORE INTO betting_interest VALUES (?,?,?,?,?,?,?)",
                            (rid + "|" + sh["pgm"], rid, sh["pgm"], sh.get("name"), 1 if sh["pgm"][-1:].isalpha() else 0,
                             "scratched" if sh["pgm"] in [] else "entered", ts))
            for provider, payload in (("timeformus", r.get("timeform")), ("equibase_changes", r.get("inputs") if (r.get("inputs") or {}).get("source") else None),
                                      ("weather:" + str((r.get("weather") or {}).get("provenance")), r.get("weather"))):
                if not payload:
                    continue
                body = json.dumps(payload, sort_keys=True, default=str)
                oid = hashlib.sha1((rid + "|" + provider + "|" + body).encode()).hexdigest()[:16]
                con.execute("INSERT OR IGNORE INTO source_observation VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (oid, provider, meta["file"], hashlib.sha1(body.encode()).hexdigest(), (payload.get("forecast_for_utc") if isinstance(payload, dict) else None),
                             (payload.get("observed_at_utc") if isinstance(payload, dict) else None) or at, at, at, rid, body, ts))
                out["observations"] = out.get("observations", 0) + con.execute("SELECT changes()").fetchone()[0]
            fid = f"{meta['file']}|{r['race_no']}"
            vec = {sh["pgm"]: {"model": sh.get("model_prob"), "market": sh.get("market_prob"), "win": sh.get("win_prob"), "score": sh.get("score"),
                               "eliminated": sh.get("eliminated"), "flags": sh.get("flags")} for sh in r.get("sheets", [])}
            cur = con.execute("INSERT OR IGNORE INTO forecast VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                              (fid, rid, meta["file"], "rule_heuristic_softmax", run.get("config_hash"), s.get("parser_version"),
                               run.get("code_version"), at, c.get("status"), json.dumps(vec), ts))
            out["forecasts"] += cur.rowcount
            for i, w in enumerate(r.get("wagers", [])):
                d = w.get("decision") or {}
                did = d.get("id") or f"{meta['file']}|{r['race_no']}|{i}"
                cur = con.execute("INSERT OR IGNORE INTO decision VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                  (did, rid, fid, meta["file"], d.get("at_utc") or at, d.get("cutoff_status") or c.get("status"), w["type"],
                                   json.dumps(w["legs"]), w.get("label"), w.get("unit"), json.dumps(w.get("min_odds_by") or w.get("min_odds")),
                                   d.get("price_basis", "morning-line"), d.get("status", "suggested"), run.get("config_hash"), ts))
                out["decisions"] += cur.rowcount
                if cur.rowcount:
                    con.execute("INSERT OR IGNORE INTO execution VALUES (?,?,?,?,?,?,?,?)",
                                (did + "|exec", did, "not_submitted", None, None, ts, "", ts))
        con.execute("COMMIT")
    rp = os.path.join(root, "results", f"{card}.results.json")
    if os.path.exists(rp):
        with open(rp, encoding="utf-8") as fh:
            res = json.load(fh)
        from handicapper.timing import off_at_utc
        con.execute("BEGIN")
        for x in res.get("races", []):
            rid_rows = con.execute("SELECT race_id, race_date FROM race WHERE card=? AND race_no=?", (card, x["race_no"])).fetchall()
            rid = rid_rows[0][0] if rid_rows else race_id(None, res.get("date"), x["race_no"])
            if not rid_rows:
                con.execute("INSERT OR IGNORE INTO race VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (rid, card, None, res.get("date"), x["race_no"], None, None, None, None, "results", ts))
            payouts = json.dumps({k: x.get(k) for k in ("win", "place", "show", "exotics")}, sort_keys=True)
            sid = hashlib.sha1((rid + "|" + json.dumps(x.get("finish")) + "|" + payouts).encode()).hexdigest()[:16]
            ver = con.execute("SELECT COUNT(*) FROM settlement WHERE race_id=?", (rid,)).fetchone()[0] + 1
            cur = con.execute("INSERT OR IGNORE INTO settlement VALUES (?,?,?,?,?,?,?,?,?,?)",
                              (sid, rid, x.get("source") or "manual", ver, json.dumps(x.get("finish")), payouts,
                               json.dumps(x.get("final_odds")), None, ts, ts))
            out["settlements"] += cur.rowcount
        con.execute("COMMIT")
    return out


def as_of(root: str, card: str, race_no: int, cutoff_utc: str, con: sqlite3.Connection | None = None) -> dict:
    """What was known for one race at cutoff_utc: the newest forecast and its decisions made at or before then,
    and the settlements (results) received at or before then.  Nothing later is returned."""
    con = con or connect(root)
    rows = con.execute("SELECT race_id FROM race WHERE card=? AND race_no=?", (card, race_no)).fetchall()
    if not rows:
        return {"race_id": None, "forecast": None, "decisions": [], "results_known": []}
    rid = rows[0][0]
    f = con.execute("SELECT forecast_id, snapshot_file, predicted_at_utc, cutoff_status, vector FROM forecast WHERE race_id=? AND predicted_at_utc<=? "
                    "ORDER BY predicted_at_utc DESC LIMIT 1", (rid, cutoff_utc)).fetchone()
    decisions = []
    if f:
        decisions = [dict(zip(("decision_id", "wager_type", "legs", "label", "status", "price_basis", "decided_at_utc"), d)) for d in
                     con.execute("SELECT decision_id, wager_type, legs, label, status, price_basis, decided_at_utc FROM decision WHERE forecast_id=?", (f[0],))]
    known = [dict(zip(("race_id", "finish", "received_at_utc"), r)) for r in
             con.execute("SELECT s.race_id, s.finish, s.received_at_utc FROM settlement s JOIN race r ON r.race_id=s.race_id "
                         "WHERE r.card=? AND s.received_at_utc<=? ORDER BY r.race_no", (card, cutoff_utc))]
    return {"race_id": rid, "forecast": None if not f else {"forecast_id": f[0], "snapshot_file": f[1], "predicted_at_utc": f[2],
                                                               "cutoff_status": f[3], "vector": json.loads(f[4])},
            "decisions": decisions, "results_known": known}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in ("import", "as-of"):
        print(__doc__); return 2
    root = argv[1]
    if argv[0] == "import":
        cards = argv[2:] or sorted(os.path.basename(p) for p in __import__("glob").glob(os.path.join(root, "data", "out", "snapshots", "*")))
        con = connect(root)
        for c in cards:
            print(c, import_card(root, c, con))
        return 0
    card, rn, at = argv[2], int(argv[3]), argv[4]
    print(json.dumps(as_of(root, card, rn, at), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
