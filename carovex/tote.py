"""Live odds and the tote board (Phase C): PuntersEdge's `/v1/racing/tote`, TVG's public US and Canadian board.

Verified against the OpenAPI document at https://api.puntersedge.online/openapi.json on 2026-11-16 (schema
`ToteRaceOut`): one call returns every race of a US Eastern race date (2 credits, whatever the number of races);
`source_race_id` is TVG's key ``tvg_<track>_<date>_<n>``; the `tote` block carries ``status`` (open / off /
official), ``pools_open``, ``final``, ``read_at`` (the provider's read of TVG, UTC), ``win_pool``, ``pools``
[{code, name, amount}], ``runners`` [{number, name, win_odds "9/1" or null, win_decimal, win_pool, morning_line
"5/2", morning_line_decimal, favorite, scratched, scratched_at, scratch_reason, place_pool, show_pool, ...}].
``history=true`` adds every read in which the odds or the WIN pool changed for one race; ``exotics=true`` adds
probables and will-pays.  Credits and the per-minute limit come back in ``X-Credits-*`` / ``X-Ratelimit-*``.

Odds convention, kept explicit on every normalised board: ``win_odds`` is pari-mutuel odds **to 1, net** as TVG
displays them (already after takeout; nothing here deducts a second takeout); ``win_decimal`` is the gross
multiple ``1 + odds``.  Before the WIN pool opens ``win_odds`` is null and only the morning line is printed; a
morning line is never labelled a tote quote.

Nothing in this module reads a rule, changes a score or places a bet.  Decisions are made elsewhere; the only
thing a board does to a decision is let the owner mark it ``paper`` or ``accepted (verified)`` against a quote.
"""
from __future__ import annotations

import gzip
import hashlib
import http.client
import json
import logging
import os
import re
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

log = logging.getLogger("carovex.tote")

PROVIDER = "puntersedge/tvg"
BASE_URL = "https://api.puntersedge.online"
KEY_ENV = "PUNTERSEDGE_API_KEY"
KEY_FILE = os.path.join("data", "private", "puntersedge.key")
USER_AGENT = "carovex-tote/1.0"

DEFAULT_TOTE = {
    "provider": "puntersedge",
    "daily_credit_cap": 60,          # credits per calendar day (UTC) this app may spend; 2 credits per board read
    "stale_seconds": 120,            # a quote older than this is shown as stale
    "heartbeat_minutes": 5,          # store an unchanged board at least this often while polling
    "poll": {"from_minutes": 60, "sparse_every": 300, "near_minutes": 15, "near_every": 60, "last_minutes": 5, "last_every": 30},
    "timeout_seconds": 15,
    "max_retries": 3,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        s = s.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ToteError(Exception):
    """A feed problem.  `kind`: auth, credits, rate_limit, network, server, malformed, cap."""

    def __init__(self, kind: str, message: str, retry_after: float | None = None, status: int | None = None):
        super().__init__(message)
        self.kind, self.retry_after, self.status = kind, retry_after, status


def redact(text: str) -> str:
    """Anything that looks like a key (long token) or an X-API-Key header value is masked before logging."""
    text = re.sub(r"(?i)(x-api-key\s*[:=]\s*)\S+", r"\1***", text)
    return re.sub(r"\b[A-Za-z0-9_\-]{24,}\b", "***", text)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
class ToteProvider:
    """Interface.  board(): the day's races (or one race) as the provider returns them, plus `meta`
    (credits, rate limit, fetched_at).  usage(): the account's credit state.  now(): the clock a poller uses."""

    name = "tote"

    def board(self, date: str | None = None, source_race_id: str | None = None, country: str = "US",
              history: bool = False, exotics: bool = False) -> dict:
        raise NotImplementedError

    def usage(self) -> dict:
        raise NotImplementedError

    def now(self) -> datetime:
        return utc_now()


def read_key(root: str | None = None) -> str | None:
    """The API key from PUNTERSEDGE_API_KEY, else data/private/puntersedge.key (ignored path).  None when
    neither exists: the request goes out without the header (a network proxy may inject it)."""
    k = os.environ.get(KEY_ENV)
    if k:
        return k.strip()
    p = os.path.join(root or ".", KEY_FILE)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            return fh.read().strip() or None
    return None


class PuntersEdgeProvider(ToteProvider):
    """Persistent HTTPS connection (through HTTPS_PROXY when set), gzip, timeouts, bounded retries with backoff,
    `Retry-After` on 429, no retry on 401/402/422.  The key never appears in logs or errors."""

    name = "puntersedge"

    def __init__(self, key: str | None = None, base_url: str = BASE_URL, timeout: float = 15.0, max_retries: int = 3,
                 sleep=time.sleep, root: str | None = None):
        self.key = key if key is not None else read_key(root)
        self.base = urlparse(base_url)
        self.timeout, self.max_retries, self._sleep = timeout, max_retries, sleep
        self._conn = None
        self.last_meta: dict = {}

    # -- connection
    def _connect(self):
        host, port = self.base.hostname, self.base.port or (443 if self.base.scheme == "https" else 80)
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") if self.base.scheme == "https" else None
        if self.base.scheme == "https":
            ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE") or None)
            if proxy:
                pu = urlparse(proxy)
                conn = http.client.HTTPSConnection(pu.hostname, pu.port or 3128, timeout=self.timeout, context=ctx)
                conn.set_tunnel(host, port)
            else:
                conn = http.client.HTTPSConnection(host, port, timeout=self.timeout, context=ctx)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=self.timeout)
        return conn

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def _headers(self) -> dict:
        h = {"Accept": "application/json", "Accept-Encoding": "gzip", "User-Agent": USER_AGENT, "Connection": "keep-alive"}
        if self.key:
            h["X-API-Key"] = self.key
        return h

    def _request(self, path: str, params: dict | None = None) -> tuple[dict | list, dict]:
        qs = urlencode({k: v for k, v in (params or {}).items() if v is not None and v is not False})
        url = path + ("?" + qs if qs else "")
        attempt, last_err = 0, None
        while attempt <= self.max_retries:
            attempt += 1
            try:
                if self._conn is None:
                    self._conn = self._connect()
                self._conn.request("GET", url, headers=self._headers())
                resp = self._conn.getresponse()
                raw = resp.read()
                headers = {k.lower(): v for k, v in resp.getheaders()}
                if headers.get("content-encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                meta = self._meta(headers, resp.status)
                self.last_meta = meta
                if resp.status == 200:
                    try:
                        return json.loads(raw.decode("utf-8")), meta
                    except ValueError as e:
                        raise ToteError("malformed", f"response is not JSON ({e})", status=200)
                body = raw.decode("utf-8", errors="replace")[:300]
                if resp.status in (401, 403):
                    raise ToteError("auth", f"HTTP {resp.status}: key missing, invalid or lacking access", status=resp.status)
                if resp.status == 402:
                    raise ToteError("credits", "HTTP 402: monthly credit allowance exhausted", status=402)
                if resp.status == 422:
                    raise ToteError("malformed", f"HTTP 422: {redact(body)}", status=422)
                if resp.status == 429:
                    ra = float(headers.get("retry-after") or 60)
                    if attempt <= self.max_retries:
                        log.warning("tote rate limited; waiting %.0fs", ra)
                        self._sleep(ra)
                        continue
                    raise ToteError("rate_limit", "HTTP 429: rate limit exceeded", retry_after=ra, status=429)
                if resp.status >= 500:
                    last_err = ToteError("server", f"HTTP {resp.status}", status=resp.status)
                else:
                    raise ToteError("network", f"HTTP {resp.status}: {redact(body)}", status=resp.status)
            except ToteError:
                raise
            except (OSError, http.client.HTTPException) as e:
                last_err = ToteError("network", f"{type(e).__name__}: {redact(str(e))}")
                self.close()
            if attempt <= self.max_retries:
                self._sleep(min(2.0 ** attempt, 20.0))
        raise last_err or ToteError("network", "request failed")

    @staticmethod
    def _meta(headers: dict, status: int) -> dict:
        def num(k):
            v = headers.get(k)
            try:
                return float(v) if v is not None and "." in v else (int(v) if v is not None else None)
            except ValueError:
                return None
        return {"fetched_at_utc": iso(utc_now()), "http_status": status,
                "credits_cost": num("x-credits-cost"), "credits_used": num("x-credits-used"), "credits_remaining": num("x-credits-remaining"),
                "credits_limit": num("x-credits-limit"), "ratelimit_limit": num("x-ratelimit-limit"), "ratelimit_remaining": num("x-ratelimit-remaining"),
                "ratelimit_reset": num("x-ratelimit-reset"), "request_id": headers.get("x-request-id")}

    # -- API
    def board(self, date=None, source_race_id=None, country="US", history=False, exotics=False) -> dict:
        params = {"date": date, "source_race_id": source_race_id, "country": country if not source_race_id else None,
                  "history": "true" if history else None, "exotics": "true" if exotics else None}
        data, meta = self._request("/v1/racing/tote", params)
        if not isinstance(data, dict) or "races" not in data:
            raise ToteError("malformed", "board without races")
        data["meta"] = meta
        return data

    def usage(self) -> dict:
        data, meta = self._request("/v1/usage")
        keep = ("plan", "credits_used", "credits_limit", "credits_remaining", "period_start", "next_reset_at", "burn_rate_per_day",
                "projected_exhaustion_date", "warning")
        return {k: data.get(k) for k in keep} | {"meta": meta}


class ReplayToteProvider(ToteProvider):
    """Recorded (synthetic) responses with a simulated clock; no key, no network.  The fixture is
    {"boards": [{"at": "...Z", "response": <board as the API returns it>}], "usage": {...}}; board() returns the
    newest recording at or before the clock, filtered to the race asked for."""

    name = "replay"

    def __init__(self, fixture: str | dict, clock: str | datetime | None = None):
        self.fx = fixture if isinstance(fixture, dict) else json.load(open(fixture, encoding="utf-8"))
        self.boards = sorted(self.fx.get("boards", []), key=lambda b: b["at"])
        self._now = parse_iso(clock) if isinstance(clock, str) else (clock or parse_iso(self.boards[0]["at"]) if self.boards else utc_now())
        self.calls = 0

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)

    def set_clock(self, when: str | datetime) -> None:
        self._now = parse_iso(when) if isinstance(when, str) else when

    def board(self, date=None, source_race_id=None, country="US", history=False, exotics=False) -> dict:
        self.calls += 1
        cands = [b for b in self.boards if parse_iso(b["at"]) <= self._now]
        if not cands:
            raise ToteError("network", "replay: nothing recorded yet at this clock")
        rec = cands[-1]
        if rec.get("error"):
            e = rec["error"]
            raise ToteError(e.get("kind", "network"), e.get("message", "replayed failure"), retry_after=e.get("retry_after"), status=e.get("status"))
        resp = json.loads(json.dumps(rec["response"]))
        if source_race_id:
            resp["races"] = [r for r in resp["races"] if r.get("source_race_id") == source_race_id]
        if date:
            resp["races"] = [r for r in resp["races"] if r.get("race_date") in (None, date)]
        if not history:
            for r in resp["races"]:
                r.pop("history", None)
        if not exotics:
            for r in resp["races"]:
                r.pop("exotics", None)
        resp["meta"] = {"fetched_at_utc": iso(self._now), "http_status": 200, "credits_cost": 2, "replay": True}
        return resp

    def usage(self) -> dict:
        return dict(self.fx.get("usage") or {"plan": "replay", "credits_used": 0, "credits_limit": 0, "credits_remaining": 0}) | {"meta": {"replay": True}}


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
ODDS_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:/|-)\s*(\d+(?:\.\d+)?)\s*$")


def odds_to_1(text) -> float | None:
    """'9/1' -> 9.0, '8/5' -> 1.6, '7-2' -> 3.5, 2.6 (decimal already) -> 2.6; anything else None."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text) if text >= 0 else None
    m = ODDS_RE.match(str(text))
    if m:
        den = float(m.group(2))
        return round(float(m.group(1)) / den, 4) if den else None
    try:
        v = float(str(text).strip())
        return v if v >= 0 else None
    except ValueError:
        return None


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f >= 0 else None     # NaN / negative pools are malformed


def interest_key(runner: dict) -> tuple[str, str]:
    """(program as text, betting interest) from TVG's `number`: 1 -> ('1','1'); '1A' -> ('1A','1')."""
    n = runner.get("program") or runner.get("saddlecloth") or runner.get("number")
    s = str(n).strip() if n is not None else "?"
    return s, re.sub(r"[A-Za-z]", "", s) or s


def normalise_board(race: dict, received_at: datetime | None = None) -> dict:
    """One `ToteRaceOut` -> the board this app stores.  Coupled entries (same betting interest) are one
    interest with their WIN pool summed; the public allocation q_i = W_i / sum W_j is over the active
    interests, reconciled with the provider's pool total and checked against normalised inverse odds."""
    t = race.get("tote") or {}
    flags = []
    runners = t.get("runners") or []
    interests: dict[str, dict] = {}
    for x in runners:
        pgm, key = interest_key(x)
        pool = _num(x.get("win_pool"))
        if x.get("win_pool") is not None and pool is None:
            flags.append(f"#{pgm}: malformed win_pool {x.get('win_pool')!r}")
        odds = odds_to_1(x.get("win_odds"))
        if x.get("win_odds") is not None and odds is None:
            flags.append(f"#{pgm}: malformed win_odds {x.get('win_odds')!r}")
        it = interests.setdefault(key, {"interest": key, "pgms": [], "names": [], "scratched": True, "win_pool": None, "odds_to_1": None,
                                        "odds_text": None, "win_decimal": None, "morning_line": None, "ml_decimal": None, "favorite": False,
                                        "scratched_at": None, "scratch_reason": None, "place_pool": None, "show_pool": None})
        it["pgms"].append(pgm); it["names"].append(x.get("name"))
        if not x.get("scratched"):
            it["scratched"] = False
            if odds is not None and (it["odds_to_1"] is None or odds < it["odds_to_1"]):
                it["odds_to_1"], it["odds_text"] = odds, str(x.get("win_odds"))
                it["win_decimal"] = _num(x.get("win_decimal")) or round(1.0 + odds, 4)
            if it["morning_line"] is None and x.get("morning_line") is not None:
                it["morning_line"], it["ml_decimal"] = str(x.get("morning_line")), _num(x.get("morning_line_decimal"))
            it["favorite"] = it["favorite"] or bool(x.get("favorite"))
        else:
            it["scratched_at"] = it["scratched_at"] or x.get("scratched_at")
            it["scratch_reason"] = it["scratch_reason"] or x.get("scratch_reason")
        if pool is not None:
            it["win_pool"] = (it["win_pool"] or 0.0) + pool
        for pk in ("place_pool", "show_pool"):
            v = _num(x.get(pk))
            if v is not None:
                it[pk] = (it[pk] or 0.0) + v
    pools = {p.get("code"): _num(p.get("amount")) for p in (t.get("pools") or []) if isinstance(p, dict) and p.get("code")}
    total = _num(t.get("win_pool"))
    if total is None:
        total = pools.get("WN")
    active = {k: v for k, v in interests.items() if not v["scratched"]}
    pool_sum = sum(v["win_pool"] or 0.0 for v in active.values())
    pools_open = bool(t.get("pools_open")) and pool_sum > 0
    allocation, from_odds = {}, {}
    if pools_open:
        for k, v in active.items():
            allocation[k] = round((v["win_pool"] or 0.0) / pool_sum, 6)
        inv = {k: 1.0 / (1.0 + v["odds_to_1"]) for k, v in active.items() if v["odds_to_1"] is not None}
        s = sum(inv.values())
        from_odds = {k: round(x / s, 6) for k, x in inv.items()} if s > 0 else {}
        missing = [k for k, v in active.items() if v["odds_to_1"] is None]
        if missing:
            flags.append("odds missing on open pool: #" + ", #".join(missing))
    reconciliation = None
    if total is not None and pool_sum > 0:
        diff = (pool_sum - total) / total if total else None
        reconciliation = {"pool_sum": round(pool_sum, 2), "pool_total": total, "diff_pct": round(100.0 * diff, 2) if diff is not None else None,
                          "ok": diff is not None and abs(diff) <= 0.02}
        if not reconciliation["ok"]:
            flags.append(f"WIN pool total {total:.0f} vs sum of interests {pool_sum:.0f}")
    if allocation and from_odds:
        gap = max(abs(allocation.get(k, 0.0) - from_odds.get(k, 0.0)) for k in set(allocation) | set(from_odds))
        reconciliation = (reconciliation or {}) | {"max_gap_pool_vs_odds": round(gap, 4)}
        if gap > 0.05:
            flags.append(f"pool shares and inverse odds disagree by {gap:.1%}")
    status = (t.get("status") or "unknown").lower()
    read_at = parse_iso(t.get("read_at"))
    board = {
        "provider": PROVIDER, "product": t.get("product"), "currency": t.get("currency"),
        "source_race_id": race.get("source_race_id"), "track_code": race.get("track_code"), "venue": race.get("venue"),
        "country": race.get("country"), "category": race.get("category"), "race_number": race.get("race_number"),
        "race_date": race.get("race_date"), "post_time_utc": race.get("post_time"),
        "status": status, "pools_open": pools_open, "final": bool(t.get("final")), "closed": status in ("off", "closed", "official"),
        "provider_read_at_utc": iso(read_at) if read_at else t.get("read_at"), "received_at_utc": iso(received_at or utc_now()),
        "win_pool_total": total, "pools": pools,
        "surface": t.get("surface"), "track_condition": t.get("track_condition"), "surface_changed_from": t.get("surface_changed_from"),
        "interests": interests, "allocation": allocation, "allocation_from_odds": from_odds, "reconciliation": reconciliation,
        "odds_convention": {"odds_to_1": "pari-mutuel odds to 1, net, as the track displays them (takeout already applied)",
                            "win_decimal": "gross multiple = 1 + odds; a payoff is rounded down to a dime per $2 at settlement"},
        "scratched": sorted(k for k, v in interests.items() if v["scratched"]),
        "flags": flags,
    }
    if race.get("history") is not None:
        board["history"] = race["history"]
    if race.get("exotics") is not None:
        board["exotics"] = race["exotics"]
    board["content_hash"] = content_hash(board)
    return board


def content_hash(board: dict) -> str:
    """What makes a board 'changed': status, pools and every interest's odds / pool / scratch state."""
    core = {"status": board.get("status"), "final": board.get("final"), "total": board.get("win_pool_total"), "pools": board.get("pools"),
            "interests": {k: (v.get("odds_text"), v.get("win_pool"), v.get("scratched")) for k, v in (board.get("interests") or {}).items()}}
    return hashlib.sha1(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()[:16]


def secs_to_post(board: dict, now: datetime) -> float | None:
    p = parse_iso(board.get("post_time_utc"))
    return (p - now).total_seconds() if p else None


def freshness(board: dict, now: datetime, stale_seconds: int = 120) -> dict:
    r = parse_iso(board.get("provider_read_at_utc"))
    age = (now - r).total_seconds() if r else None
    return {"age_seconds": round(age) if age is not None else None, "stale": age is None or age > stale_seconds}


# ---------------------------------------------------------------------------
# Polling policy and credit cap
# ---------------------------------------------------------------------------
class PollPlan:
    """Seconds to wait before the next read, given the seconds to post of the nearest open race of interest:
    nothing before `from_minutes`, `sparse_every` until `near_minutes`, `near_every` until `last_minutes`,
    `last_every` after that and while the race is still open after post; None once off / closed / official."""

    def __init__(self, cfg: dict | None = None):
        self.c = dict(DEFAULT_TOTE["poll"], **((cfg or {}).get("poll") or {}))

    def interval(self, secs: float | None, closed: bool = False) -> float | None:
        if closed:
            return None
        if secs is None:
            return float(self.c["sparse_every"])
        m = secs / 60.0
        if m > self.c["from_minutes"]:
            return None
        if m > self.c["near_minutes"]:
            return float(self.c["sparse_every"])
        if m > self.c["last_minutes"]:
            return float(self.c["near_every"])
        return float(self.c["last_every"])


class CreditLedger:
    """Credits spent per UTC day, kept in data/private/tote_usage.json (ignored path), so the daily cap holds
    across processes.  Also keeps the last `X-Credits-*` values the provider reported."""

    def __init__(self, root: str, cap: int):
        self.path = os.path.join(root, "data", "private", "tote_usage.json")
        self.cap = cap
        self.data = {"days": {}, "last": {}}
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as fh:
                    self.data = json.load(fh)
            except (OSError, ValueError):
                pass

    def today(self, now: datetime | None = None) -> str:
        return (now or utc_now()).strftime("%Y-%m-%d")

    def spent(self, now=None) -> int:
        return int(self.data["days"].get(self.today(now), 0))

    def can_spend(self, credits: int = 2, now=None) -> bool:
        return self.spent(now) + credits <= self.cap

    def record(self, meta: dict, now=None) -> None:
        cost = meta.get("credits_cost")
        self.data["days"][self.today(now)] = self.spent(now) + int(cost if cost is not None else 2)
        self.data["last"] = {k: meta.get(k) for k in ("credits_used", "credits_remaining", "credits_limit", "ratelimit_remaining", "fetched_at_utc")}
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=1)
        os.replace(tmp, self.path)

    def status(self, now=None) -> dict:
        return {"spent_today": self.spent(now), "cap": self.cap, "provider": self.data.get("last") or {}}


# ---------------------------------------------------------------------------
# Capture: immutable observations in the ledger and raw payloads under data/private/tote
# ---------------------------------------------------------------------------
def observation_id(board: dict) -> str:
    return hashlib.sha1(f"{board.get('source_race_id')}|{board.get('provider_read_at_utc')}|{board.get('content_hash')}".encode()).hexdigest()[:16]


class Capture:
    """Stores every changed board (and a heartbeat when unchanged for `heartbeat_minutes`) as a
    `source_observation` row keyed by content, plus the normalised payload as a JSON file.  Never updates a row."""

    def __init__(self, root: str, heartbeat_minutes: int = 5, con=None):
        from carovex.ledger import connect
        self.root = root
        self.con = con or connect(root)
        self.heartbeat = timedelta(minutes=heartbeat_minutes)
        self.dir = os.path.join(root, "data", "private", "tote")

    def latest(self, race_id: str) -> dict | None:
        row = self.con.execute("SELECT observation_id, payload, received_at_utc FROM source_observation WHERE race_id=? AND provider=? "
                               "ORDER BY received_at_utc DESC, rowid DESC LIMIT 1", (race_id, PROVIDER)).fetchone()
        if not row:
            return None
        b = json.loads(row[1]); b["observation_id"] = row[0]
        return b

    def store(self, board: dict, race_id: str, now: datetime | None = None, kind: str = "board") -> dict:
        """Returns {"stored": bool, "observation_id", "reason"}.  Unchanged boards are stored only as heartbeats."""
        now = now or utc_now()
        prev = self.latest(race_id)
        if prev and prev.get("content_hash") == board.get("content_hash") and kind == "board":
            last = parse_iso(prev.get("received_at_utc"))
            if last and now - last < self.heartbeat:
                return {"stored": False, "observation_id": prev.get("observation_id"), "reason": "unchanged"}
            kind = "heartbeat"
        oid = observation_id(board) if kind == "board" else hashlib.sha1(f"{kind}|{race_id}|{iso(now)}|{board.get('content_hash')}".encode()).hexdigest()[:16]
        payload = dict(board, kind=kind)
        body = json.dumps(payload, sort_keys=True, default=str)
        from carovex.ledger import now_utc
        cur = self.con.execute("INSERT OR IGNORE INTO source_observation VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                               (oid, PROVIDER, board.get("source_race_id"), hashlib.sha1(body.encode()).hexdigest(), board.get("post_time_utc"),
                                board.get("provider_read_at_utc"), iso(now), iso(now), race_id, body, now_utc()))
        self.con.commit()
        if cur.rowcount:
            d = os.path.join(self.dir, str(board.get("race_date") or "undated"), str(board.get("source_race_id") or race_id).replace("|", "_"))
            os.makedirs(d, exist_ok=True)
            fn = os.path.join(d, f"{(board.get('provider_read_at_utc') or iso(now)).replace(':', '')}_{oid}.json")
            if not os.path.exists(fn):
                with open(fn, "w", encoding="utf-8") as fh:
                    fh.write(body)
        return {"stored": bool(cur.rowcount), "observation_id": oid, "reason": kind}

    def history(self, race_id: str, limit: int = 500) -> list[dict]:
        rows = self.con.execute("SELECT observation_id, payload FROM source_observation WHERE race_id=? AND provider=? "
                                "ORDER BY received_at_utc ASC, rowid ASC LIMIT ?", (race_id, PROVIDER, limit)).fetchall()
        out = []
        for oid, payload in rows:
            b = json.loads(payload); b["observation_id"] = oid; out.append(b)
        return out


# ---------------------------------------------------------------------------
# The poller: one card, one read, every race of that track and day
# ---------------------------------------------------------------------------
def tvg_code(track_code: str | None, cfg: dict | None) -> str | None:
    """TVG's code for a Brisnet track code (tracks.<code>.tvg_code when they differ; BEL, CD, DMR, GP agree)."""
    if not track_code:
        return None
    t = ((cfg or {}).get("tracks") or {}).get(track_code.upper()) or {}
    return (t.get("tvg_code") or track_code).upper()


class TotePoller:
    """Reads the day's board for a card's track, stores changed boards, and says when to read next.
    A feed failure sets `status` and disables decisions; it never raises out of poll()."""

    def __init__(self, root: str, provider: ToteProvider, cfg: dict | None = None, con=None):
        full = cfg or {}
        self.cfg = dict(DEFAULT_TOTE, **(full.get("tote") or {}))
        self.full = full
        self.root = root
        self.provider = provider
        self.plan = PollPlan(self.cfg)
        self.credits = CreditLedger(root, int(self.cfg["daily_credit_cap"]))
        self.capture = Capture(root, int(self.cfg["heartbeat_minutes"]), con=con)
        self.status = {"feed": "idle", "reason": None, "last_read_utc": None, "decisions_enabled": True}

    def _fail(self, kind: str, msg: str) -> dict:
        self.status = {"feed": "disabled" if kind in ("auth", "credits", "cap") else "error", "reason": f"{kind}: {redact(msg)}",
                       "last_read_utc": self.status.get("last_read_utc"), "decisions_enabled": False}
        log.warning("tote feed %s", self.status["reason"])
        return {"ok": False, "status": self.status, "races": {}, "next_in": None}

    def poll(self, track_code: str, date: str, races: list[int] | None = None, source_race_id: str | None = None,
             history: bool = False, exotics: bool = False) -> dict:
        """One read.  Returns {"ok", "status", "races": {race_no: board}, "next_in": seconds or None, "credits"}."""
        now = self.provider.now()
        if not self.credits.can_spend(2, now):
            return self._fail("cap", f"daily credit cap {self.credits.cap} reached ({self.credits.spent(now)} spent)")
        try:
            resp = self.provider.board(date=None if source_race_id else date, source_race_id=source_race_id, history=history, exotics=exotics)
        except ToteError as e:
            return self._fail(e.kind, str(e))
        meta = resp.get("meta") or {}
        self.credits.record(meta, now)
        code = tvg_code(track_code, self.full)
        out, nearest, all_closed = {}, None, True
        for race in resp.get("races", []):
            if code and (race.get("track_code") or "").upper() != code:
                continue
            if races and race.get("race_number") not in races:
                continue
            try:
                board = normalise_board(race, now)
            except Exception as e:   # one malformed race never stops the others
                log.warning("tote: race %s unreadable: %s", race.get("source_race_id"), redact(str(e)))
                continue
            from carovex.ledger import race_id as rid
            stored = self.capture.store(board, rid(track_code.upper(), date, int(board["race_number"])), now)
            board["observation_id"] = stored["observation_id"]
            board["freshness"] = freshness(board, now, int(self.cfg["stale_seconds"]))
            board["secs_to_post"] = secs_to_post(board, now)
            out[int(board["race_number"])] = board
            if not board["closed"]:
                all_closed = False
                if board["secs_to_post"] is not None and (nearest is None or board["secs_to_post"] < nearest):
                    nearest = board["secs_to_post"]
        self.status = {"feed": "ok", "reason": None, "last_read_utc": iso(now), "decisions_enabled": True,
                       "credits": self.credits.status(now), "provider_meta": {k: meta.get(k) for k in ("credits_remaining", "credits_limit", "ratelimit_remaining")}}
        if not out:
            self.status["reason"] = f"no races for {code or track_code} on {date} in the board"
        nxt = None if all_closed else self.plan.interval(nearest if nearest is not None else None, closed=False)
        if nearest is not None and nearest / 60.0 > self.plan.c["from_minutes"]:
            nxt = None
        return {"ok": True, "status": self.status, "races": out, "next_in": nxt, "credits": self.credits.status(now)}

    def final(self, track_code: str, date: str, race_no: int, source_race_id: str | None = None) -> dict:
        """After a race is official: the final board with its history and exotics, stored once (kind 'final')."""
        srid = source_race_id or f"tvg_{tvg_code(track_code, self.full)}_{date}_{race_no}"
        res = self.poll(track_code, date, races=[race_no], source_race_id=srid, history=True, exotics=True)
        if res["ok"] and race_no in res["races"]:
            b = res["races"][race_no]
            from carovex.ledger import race_id as rid
            self.capture.store(b, rid(track_code.upper(), date, race_no), self.provider.now(), kind="final")
        return res


# ---------------------------------------------------------------------------
# Decisions against a quote: the only path to price_basis "observed"
# ---------------------------------------------------------------------------
def quote_for(board: dict | None, legs: list[list[str]]) -> dict | None:
    """The current quote for a single-horse wager (win / place / show): odds to 1 and allocation for its interest."""
    if not board or not legs or len(legs) != 1 or len(legs[0]) != 1:
        return None
    pgm = legs[0][0]
    key = re.sub(r"[A-Za-z]", "", str(pgm)) or str(pgm)
    it = (board.get("interests") or {}).get(key)
    if not it:
        return None
    return {"interest": key, "odds_to_1": it.get("odds_to_1"), "odds_text": it.get("odds_text"), "win_decimal": it.get("win_decimal"),
            "allocation": (board.get("allocation") or {}).get(key), "scratched": it.get("scratched"), "pools_open": board.get("pools_open"),
            "status": board.get("status"), "observation_id": board.get("observation_id"), "provider_read_at_utc": board.get("provider_read_at_utc")}


def mark_decision(root: str, card: str, decision_id: str, status: str, quote: dict | None, note: str = "", con=None) -> dict:
    """Record the owner's word on a suggested wager: `paper` (intends) or `accepted` (placed elsewhere and says so),
    with the quote snapshot id.  Stored in the ledger's execution table and returned for the Desk's state file."""
    if status not in ("paper", "accepted", "suggested"):
        raise ValueError("status must be paper, accepted or suggested")
    from carovex.ledger import connect, now_utc
    con = con or connect(root)
    ts = now_utc()
    eid = f"{decision_id}|{status}|{ts}"
    exists = con.execute("SELECT 1 FROM decision WHERE decision_id=?", (decision_id,)).fetchone()
    if exists:
        con.execute("INSERT OR IGNORE INTO execution VALUES (?,?,?,?,?,?,?,?)",
                    (eid, decision_id, "accepted_verified" if status == "accepted" else status, (quote or {}).get("observation_id"),
                     "owner" if status == "accepted" else None, ts, note or "", ts))
        con.commit()
    rec = {"decision_id": decision_id, "status": status, "price_basis": "observed" if status == "accepted" else "morning-line",
           "quote": quote, "at_utc": ts, "note": note, "verified_by": "owner" if status == "accepted" else None, "in_ledger": bool(exists)}
    return rec


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cfg(root: str) -> dict:
    p = os.path.join(root, "rules_config.json")
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def _print_board(b: dict) -> None:
    fr = b.get("freshness") or {}
    print(f"{b['track_code']} R{b['race_number']} {b['status']}{' FINAL' if b['final'] else ''} pool ${b['win_pool_total'] or 0:,.0f} "
          f"read {b['provider_read_at_utc']} ({fr.get('age_seconds')}s{' STALE' if fr.get('stale') else ''}) post {b['post_time_utc']}"
          + (f"  flags: {'; '.join(b['flags'])}" if b["flags"] else ""))
    for k, it in sorted(b["interests"].items(), key=lambda kv: int(re.sub(r"\D", "", kv[0]) or 0)):
        q = b["allocation"].get(k)
        print(f"   #{'/'.join(it['pgms']):<5} {('SCR ' + (it['scratch_reason'] or '')) if it['scratched'] else (it['odds_text'] or '-'):<18} "
              f"ML {it['morning_line'] or '-':<6} win ${it['win_pool'] or 0:>9,.0f} q {q if q is not None else '-'}  {it['names'][0] or ''}")


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m carovex.tote", description="PuntersEdge tote board: sample, poll, replay, result")
    ap.add_argument("--root", default=os.getcwd())
    ap.add_argument("--replay", help="use a replay fixture instead of the network")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample", help="today's board: tracks, races and credits (2 credits)").add_argument("--date")
    p = sub.add_parser("poll", help="read a card's track once (or --loop until off/official/cap)")
    p.add_argument("card"); p.add_argument("race", nargs="?", type=int); p.add_argument("--loop", action="store_true")
    r = sub.add_parser("result", help="final board with history and exotics for one race (2 credits)")
    r.add_argument("card"); r.add_argument("race", type=int)
    sub.add_parser("replay", help="run a replay fixture through the poller").add_argument("fixture")
    sub.add_parser("usage", help="credits used / remaining (free)")
    a = ap.parse_args(argv)
    root = a.root
    cfg = _cfg(root) if os.path.exists(os.path.join(root, "rules_config.json")) else {}
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if a.cmd == "replay":
        prov = ReplayToteProvider(a.fixture)
        poller = TotePoller(root, prov, cfg)
        fx = prov.fx
        res = poller.poll(fx.get("track_code", "SYN"), fx.get("date", prov.boards[0]["response"]["date"]))
        for b in res["races"].values():
            _print_board(b)
        print(json.dumps(res["status"], indent=1))
        return 0
    prov = ReplayToteProvider(a.replay) if a.replay else PuntersEdgeProvider(root=root, timeout=cfg.get("tote", {}).get("timeout_seconds", 15))
    if a.cmd == "usage":
        print(json.dumps(prov.usage(), indent=1)); return 0
    if a.cmd == "sample":
        resp = prov.board(date=a.date)
        from collections import Counter
        print(f"{resp['date']} {len(resp['races'])} races; credits cost {resp['meta'].get('credits_cost')}, remaining {resp['meta'].get('credits_remaining')}")
        for (code, venue), n in sorted(Counter((r["track_code"], r["venue"]) for r in resp["races"]).items()):
            sts = Counter((r.get("tote") or {}).get("status") for r in resp["races"] if r["track_code"] == code)
            print(f"  {code:<5} {venue:<28} {n:>2} races  {dict(sts)}")
        return 0
    # poll / result need the card's track and date
    from handicapper.pipeline import load_card
    src = next((os.path.join(root, "data", "out", f"{a.card}.card.json"), os.path.join(root, "data", "pps", f"{a.card}.pdf")), None)
    for cand in (os.path.join(root, "data", "out", f"{a.card}.card.json"), os.path.join(root, "data", "pps", f"{a.card}.pdf")):
        if os.path.exists(cand):
            src = cand; break
    card, _ = load_card(src)
    track, date = (card.get("track_code") or "").upper(), card.get("date")
    poller = TotePoller(root, prov, cfg)
    if a.cmd == "result":
        res = poller.final(track, date, a.race)
    else:
        while True:
            res = poller.poll(track, date, races=[a.race] if a.race else None)
            for b in res["races"].values():
                _print_board(b)
            print("status:", json.dumps(res["status"]))
            if not a.loop or not res["ok"] or res["next_in"] is None:
                break
            print(f"next read in {res['next_in']:.0f}s"); time.sleep(res["next_in"])
    for b in res["races"].values():
        _print_board(b)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
