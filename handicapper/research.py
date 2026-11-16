"""Research layer (Phase D): what the engine thinks, what the public thinks, and what would be a bet, kept apart
and labelled.  Nothing here claims calibration; `model_status` is printed on every vector.

Per betting interest (1 and 1A are one interest):
  p_rule_heuristic  today's softmax of the ability score, renormalised over every legal starter with a floor for
                    the eliminated ones (eliminations stay hard for *selection*; their pool share is not wished
                    away here).  Labelled heuristic.
  q_live_market     the tote's public allocation W_i / sum W_j (Phase C) when the board is open, reconciled and
                    fresh; else None with the reason.
  p_market_anchor   p_i proportional to q_i^alpha * exp(beta * z_i), alpha = 1 and beta = 0 by default (market
                    only); z_i is the engine score standardised over the live field.  When no live market exists the
                    anchor uses the renormalised morning line and says so (`anchor_source`).
  p_final_model     None until Phase E validates one.

EV and price at fixed net odds O (to 1): EV = p * (O + 1) - 1 per dollar; the odds needed for a target return tau
with costs and rebate: O_min = (1 + tau + costs - rebate) / p - 1; break-even odds 1 / p - 1.  Under pari-mutuel
uncertainty three scenarios are shown: the current quote, an adverse drift of the quote, and the break-even.

NO_BET reason codes gate a paper BET; today the model is UNTRAINED so every single-horse wager is NO_BET
(code UNTRAINED_MODEL) and exotics and multi-race tickets are `candidate, unpriced`.  An EXPERIMENTAL flag marks
the owner's exploratory paper trades; it is never a validated edge.

Place and show (heuristic until Phase E validates it): the Harville expansion of the win vector gives each horse's
chance of finishing in the first two and the first three; every race names at least one place and one show
candidate with a minimum $2 price.
"""
from __future__ import annotations

import math
import re

DEFAULT_RESEARCH = {
    "model_status": "UNTRAINED",     # UNTRAINED | RESEARCH_ONLY | VALIDATED (Phase E sets the latter two)
    "alpha": 1.0,                    # market anchor exponent on q
    "beta": 0.0,                     # weight of the standardised engine score in the anchor (0 = market only)
    "research_floor": 0.02,          # probability floor per eliminated starter in the research vector
    "market_max_age_seconds": 120,   # a live quote older than this is stale for research
}
DEFAULT_PRICING = {
    "tau": 0.15,                     # target return per dollar for a win bet (replaces fair odds x 1.15)
    "costs": 0.0,                    # per-dollar costs (none at a pari-mutuel window)
    "rebate": 0.0,                   # per-dollar rebate (none)
    "adverse_drift": 0.20,           # scenario: the quote shortens by this share before the pool closes
    "place_show_tau": 0.10,          # target return for a place or show candidate's minimum $2 price
}
MODEL_STATUSES = ("UNTRAINED", "RESEARCH_ONLY", "VALIDATED")
NO_BET = ("STALE_DATA", "UNMATCHED_RUNNER", "SCRATCH_OR_COUPLED_MISMATCH", "MARKET_CLOSED", "UNTRAINED_MODEL", "NO_VALIDATED_EDGE",
          "INSUFFICIENT_PRICE", "POOL_UNCERTAINTY", "BANKROLL_CAP", "INVALID_VECTOR", "UNPRICED_EXOTIC_POOL")


def interest_of(pgm: str) -> str:
    return re.sub(r"[A-Za-z]", "", str(pgm)) or str(pgm)


def validate_research(cfg: dict | None) -> dict:
    c = dict(DEFAULT_RESEARCH, **(cfg or {}))
    bad = []
    if c["model_status"] not in MODEL_STATUSES:
        bad.append(f"model_status must be one of {MODEL_STATUSES}, not {c['model_status']!r}")
    for k, lo, hi in (("alpha", 0.0, 5.0), ("beta", -5.0, 5.0), ("research_floor", 0.0, 0.2)):
        try:
            if not (lo <= float(c[k]) <= hi):
                bad.append(f"{k} must be between {lo} and {hi}, not {c[k]!r}")
        except (TypeError, ValueError):
            bad.append(f"{k} must be a number, not {c[k]!r}")
    if bad:
        raise ValueError("research settings: " + "; ".join(bad))
    return c


def validate_pricing(cfg: dict | None) -> dict:
    c = dict(DEFAULT_PRICING, **(cfg or {}))
    bad = []
    for k, lo, hi in (("tau", 0.0, 2.0), ("costs", 0.0, 1.0), ("rebate", 0.0, 1.0), ("adverse_drift", 0.0, 0.9), ("place_show_tau", 0.0, 2.0)):
        try:
            if not (lo <= float(c[k]) <= hi):
                bad.append(f"{k} must be between {lo} and {hi}, not {c[k]!r}")
        except (TypeError, ValueError):
            bad.append(f"{k} must be a number, not {c[k]!r}")
    if not bad and 1.0 + c["tau"] + c["costs"] - c["rebate"] <= 0:
        bad.append("1 + tau + costs - rebate must be positive")
    if bad:
        raise ValueError("pricing settings: " + "; ".join(bad))
    return c


# ---------------------------------------------------------------------------
# EV and price
# ---------------------------------------------------------------------------
def ev(p: float, odds_net: float) -> float | None:
    """Expected value per dollar at fixed net odds to 1."""
    if p is None or odds_net is None or p <= 0:
        return None
    return round(p * (odds_net + 1.0) - 1.0, 4)


def o_min(p: float, cfg: dict | None = None) -> float | None:
    """Odds to 1 that return `tau` per dollar after costs and rebate: (1 + tau + costs - rebate) / p - 1."""
    c = validate_pricing(cfg)
    if p is None or p <= 0:
        return None
    return round((1.0 + c["tau"] + c["costs"] - c["rebate"]) / p - 1.0, 2)


def break_even(p: float) -> float | None:
    return round(1.0 / p - 1.0, 2) if p and p > 0 else None


def scenarios(p: float, quote: float | None, cfg: dict | None = None) -> dict:
    """Research diagnostics for one horse: EV at the current quote, after an adverse drift, and the break-even."""
    c = validate_pricing(cfg)
    out = {"label": "research diagnostics (heuristic probability; not a validated edge)", "p": round(p, 4) if p else None,
           "break_even_odds": break_even(p), "o_min": o_min(p, c), "tau": c["tau"]}
    if quote is not None and p:
        drift = round(quote * (1.0 - c["adverse_drift"]), 2)
        out |= {"quote_odds": quote, "ev_at_quote": ev(p, quote), "adverse_quote_odds": drift, "ev_after_drift": ev(p, drift),
                "quote_meets_o_min": quote >= out["o_min"]}
    else:
        out |= {"quote_odds": None, "ev_at_quote": None, "adverse_quote_odds": None, "ev_after_drift": None, "quote_meets_o_min": None}
    return out


# ---------------------------------------------------------------------------
# Probability vectors
# ---------------------------------------------------------------------------
def _norm(v: dict) -> dict:
    z = sum(v.values())
    return {k: x / z for k, x in v.items()} if z > 0 else {}


def check_vector(v: dict | None, legal: set | None = None) -> list[str]:
    """Problems with a probability vector: not finite, negative, not summing to one, a legal starter with no mass."""
    if not v:
        return ["empty vector"]
    bad = []
    for k, x in v.items():
        if not isinstance(x, (int, float)) or not math.isfinite(x):
            bad.append(f"{k}: not finite")
        elif x < 0:
            bad.append(f"{k}: negative")
    if not bad and abs(sum(v.values()) - 1.0) > 1e-6:
        bad.append(f"sums to {sum(v.values()):.6f}")
    if legal:
        for k in legal:
            if v.get(k, 0.0) <= 0:
                bad.append(f"{k}: legal starter with no mass")
    return bad


def research_vector(sheets: list[dict], board: dict | None, cfg: dict | None = None, now_age_seconds: float | None = None) -> dict:
    """The research probabilities for one race over betting interests.  `sheets` are the engine's rows (pgm,
    score, model_prob, ml_decimal, eliminated, flags); `board` the latest normalised tote board or None."""
    c = validate_research(cfg)
    running = [s for s in sheets if not s.get("flags")]          # AE / MTO alternates are not legal starters yet
    live = [s for s in running if not s.get("eliminated")]
    by_int: dict[str, list[dict]] = {}
    for s in running:
        by_int.setdefault(interest_of(s["pgm"]), []).append(s)
    legal = set(by_int)
    # p_rule_heuristic: the softmax over live horses, a floor for each eliminated interest, renormalised
    raw = {}
    for k, rows in by_int.items():
        p = sum(float(s.get("model_prob") or 0.0) for s in rows if not s.get("eliminated"))
        if p <= 0:
            p = c["research_floor"]
        raw[k] = p
    p_rule = _norm(raw)
    # q_live_market
    q, q_reason = None, None
    if board is None:
        q_reason = "no tote board"
    elif not board.get("pools_open"):
        q_reason = "pools not open"
    elif board.get("closed") and not board.get("final"):
        q_reason = "market closed"
    elif board.get("reconciliation") and board["reconciliation"].get("ok") is False:
        q_reason = "pool total does not reconcile"
    else:
        age = now_age_seconds if now_age_seconds is not None else (board.get("freshness") or {}).get("age_seconds")
        if age is not None and age > c["market_max_age_seconds"] and not board.get("final"):
            q_reason = f"quote is {age:.0f}s old"
        else:
            alloc = board.get("allocation") or {}
            q = {k: alloc.get(k, 0.0) for k in legal}
            missing = [k for k in legal if k not in alloc and not (board.get("interests") or {}).get(k, {}).get("scratched")]
            if missing:
                q_reason = "interest missing from the board: #" + ", #".join(sorted(missing))
                q = None
            else:
                q = _norm(q) or None                      # zero-mass legal starters stay in the vector and are reported
                if q is None:
                    q_reason = "no money in the pool"
    # p_market_anchor
    scores = {k: max(float(s.get("score") or 0.0) for s in rows) for k, rows in by_int.items()}
    live_scores = [scores[k] for k in legal if any(not s.get("eliminated") for s in by_int[k])]
    mu = sum(live_scores) / len(live_scores) if live_scores else 0.0
    sd = math.sqrt(sum((x - mu) ** 2 for x in live_scores) / len(live_scores)) if len(live_scores) > 1 else 0.0
    z = {k: ((scores[k] - mu) / sd if sd > 0 else 0.0) for k in legal}
    anchor_src = None
    base = None
    if q:
        base, anchor_src = q, "tote"
    else:
        mls = {k: min((float(s["ml_decimal"]) for s in rows if s.get("ml_decimal") is not None), default=None) for k, rows in by_int.items()}
        if all(v is not None for v in mls.values()) and mls:
            base, anchor_src = _norm({k: 1.0 / (v + 1.0) for k, v in mls.items()}), "morning-line"
    anchor = None
    if base:
        anchor = _norm({k: (base.get(k, 0.0) ** c["alpha"]) * math.exp(c["beta"] * z[k]) for k in legal})
    out = {"interests": {k: sorted(s["pgm"] for s in rows) for k, rows in by_int.items()},
           "p_rule_heuristic": {k: round(v, 4) for k, v in p_rule.items()}, "p_rule_label": "heuristic (softmax of the ability score; eliminated starters at the research floor)",
           "q_live_market": {k: round(v, 4) for k, v in q.items()} if q else None, "q_reason": q_reason,
           "p_market_anchor": {k: round(v, 4) for k, v in anchor.items()} if anchor else None, "anchor_source": anchor_src,
           "anchor_params": {"alpha": c["alpha"], "beta": c["beta"]}, "z": {k: round(v, 3) for k, v in z.items()},
           "p_final_model": None, "model_status": c["model_status"],
           "eliminated": sorted(k for k, rows in by_int.items() if all(s.get("eliminated") for s in rows)),
           "problems": check_vector(p_rule, legal)}
    for name in ("q_live_market", "p_market_anchor"):
        if out[name]:
            probs = check_vector(out[name], legal)
            if probs:
                out["problems"].extend(f"{name}: {x}" for x in probs)
    return out


# ---------------------------------------------------------------------------
# Place and show (Harville)
# ---------------------------------------------------------------------------
def harville(win: dict) -> dict:
    """{pgm: {"win", "place" (first two), "show" (first three)}} from a win vector (renormalised to one)."""
    p = _norm({k: float(v) for k, v in win.items() if v and v > 0})
    out = {}
    keys = list(p)
    for i in keys:
        pi = p[i]
        second = sum(p[j] * pi / (1.0 - p[j]) for j in keys if j != i and p[j] < 1.0)
        third = 0.0
        for j in keys:
            if j == i:
                continue
            for k in keys:
                if k in (i, j):
                    continue
                rest = 1.0 - p[j] - p[k]
                if rest > 0:
                    third += p[j] * (p[k] / (1.0 - p[j])) * (pi / rest)
        out[i] = {"win": round(pi, 4), "place": round(min(1.0, pi + second), 4), "show": round(min(1.0, pi + second + third), 4)}
    for k in win:
        out.setdefault(k, {"win": 0.0, "place": 0.0, "show": 0.0})
    return out


def min_price_2(p: float, cfg: dict | None = None) -> float | None:
    """Minimum $2 payoff for a place or show candidate: 2 x (1 + place_show_tau) / p, rounded up to the dime."""
    c = validate_pricing(cfg)
    if not p or p <= 0:
        return None
    return math.ceil(2.0 * (1.0 + c["place_show_tau"]) / p * 10.0) / 10.0


def place_show_candidates(r: dict, cfg: dict | None = None) -> dict:
    """At least one place and one show candidate per race, each with a minimum $2 price.  The first candidate is
    the top pick when its win price fails; when the top pick is already a win bet, the second-ranked live horse.
    Labelled heuristic (Harville on the blended win vector over the live horses)."""
    live = [s for s in r["sheets"] if not s["eliminated"] and not s["flags"]]
    if not live:
        return {"place": [], "show": [], "probs": {}, "note": "no live horses"}
    hv = harville({s["pgm"]: s.get("win_prob") or 0.0 for s in live})
    win_bet = {k for w in r.get("wagers", []) if w["type"] == "WIN" for k in w["legs"][0]}
    top = live[0]["pgm"]
    first = live[1]["pgm"] if (top in win_bet and len(live) > 1) else top
    why = ("top pick is a win bet; the second horse is the place/show candidate" if first != top else
           "top pick's win price fails (or no win bet): it is the place/show candidate")
    out = {"probs": hv, "label": "heuristic: Harville expansion of the blended win vector", "note": why, "place": [], "show": []}
    for kind in ("place", "show"):
        p = hv[first][kind]
        out[kind].append({"pgm": first, "prob": p, "min_price_2": min_price_2(p, cfg)})
    return out


def place_show_wagers(r: dict, cfg: dict | None = None, units: dict | None = None) -> tuple[list[dict], list[str]]:
    """PLACE and SHOW wager structures (one candidate each) with their minimum $2 prices, and text lines."""
    from .wagering import make_wager
    ps = place_show_candidates(r, cfg)
    names = {s["pgm"]: s for s in r["sheets"]}
    W, T = [], []
    for kind, wtype in (("place", "PLACE"), ("show", "SHOW")):
        for c in ps.get(kind, []):
            nm = names.get(c["pgm"], {}).get("name", "")
            label = f"{wtype} #{c['pgm']} {nm} (chance {c['prob']:.0%}; needs ${c['min_price_2']:.2f} per $2)"
            w = make_wager(wtype, [[c["pgm"]]], False, label, "other", r["race_no"]) | {"min_price_2": c["min_price_2"], "prob": c["prob"],
                                                                                        "prob_label": ps.get("label")}
            W.append(w); T.append(label)
    if T:
        T.append(f"place/show candidates: {ps.get('note')}")
    r["place_show"] = {k: v for k, v in ps.items() if k != "probs"} | {"probs": ps.get("probs")}
    return W, T


# ---------------------------------------------------------------------------
# NO_BET gates on single-horse wagers; exotics are candidates, unpriced
# ---------------------------------------------------------------------------
def gate_wager(w: dict, rv: dict, board: dict | None, cfg: dict | None = None, pricing: dict | None = None,
               bankroll_ok: bool = True) -> dict:
    """{"decision": "BET"|"NO_BET"|"CANDIDATE", "codes": [...], "label", "experimental", "diagnostics"}."""
    c = validate_research(cfg)
    if w["type"] not in ("WIN", "PLACE", "SHOW"):
        return {"decision": "CANDIDATE", "codes": ["UNPRICED_EXOTIC_POOL"], "label": "candidate, unpriced", "experimental": False, "diagnostics": None}
    codes = []
    pgm = w["legs"][0][0] if w.get("legs") and w["legs"][0] else None
    key = interest_of(pgm) if pgm else None
    if rv.get("problems"):
        codes.append("INVALID_VECTOR")
    if key not in (rv.get("p_rule_heuristic") or {}):
        codes.append("UNMATCHED_RUNNER")
    if c["model_status"] != "VALIDATED":
        codes.append("UNTRAINED_MODEL")
    diag = None
    if board is not None and key:
        it = (board.get("interests") or {}).get(key)
        if it is None:
            codes.append("UNMATCHED_RUNNER") if "UNMATCHED_RUNNER" not in codes else None
        elif it.get("scratched") or sorted(it.get("pgms") or []) != sorted(rv.get("interests", {}).get(key, [])):
            codes.append("SCRATCH_OR_COUPLED_MISMATCH")
        if board.get("closed") and not board.get("final"):
            codes.append("MARKET_CLOSED")
        if (board.get("freshness") or {}).get("stale") and not board.get("final"):
            codes.append("STALE_DATA")
        if not board.get("pools_open") or (board.get("reconciliation") or {}).get("ok") is False:
            codes.append("POOL_UNCERTAINTY")
        quote = (it or {}).get("odds_to_1") if it else None
        p = (rv.get("p_final_model") or rv.get("p_rule_heuristic") or {}).get(key)
        if w["type"] == "WIN" and p:
            diag = scenarios(p, quote, pricing)
            if quote is None or diag["ev_at_quote"] is None or diag["ev_at_quote"] <= 0:
                codes.append("NO_VALIDATED_EDGE")
            elif not diag["quote_meets_o_min"]:
                codes.append("INSUFFICIENT_PRICE")
    else:
        if board is None:
            codes.append("STALE_DATA")          # no quote at all
        codes.append("NO_VALIDATED_EDGE")
    if not bankroll_ok:
        codes.append("BANKROLL_CAP")
    codes = list(dict.fromkeys(codes))
    decision = "BET" if not codes else "NO_BET"
    return {"decision": decision, "codes": codes, "label": "paper BET: every gate passed" if decision == "BET" else "NO_BET: " + ", ".join(codes),
            "experimental": False, "diagnostics": diag}


def attach(result: dict, boards: dict | None = None, cfg: dict | None = None) -> None:
    """Add the research layer to a scored card: per race `research` (vectors, status) and per wager `research`
    (gate decision, codes, diagnostics).  Picks, scores and tickets are untouched."""
    rcfg = validate_research((cfg or {}).get("research"))
    pcfg = validate_pricing((cfg or {}).get("pricing"))
    boards = boards or {}
    for r in result.get("races", []):
        board = boards.get(r["race_no"]) or boards.get(str(r["race_no"]))
        rv = research_vector(r["sheets"], board, rcfg)
        r["research"] = rv
        for s in r["sheets"]:
            key = interest_of(s["pgm"])
            s["research"] = {"interest": key, "p_rule_heuristic": rv["p_rule_heuristic"].get(key), "q_live_market": (rv["q_live_market"] or {}).get(key),
                             "p_market_anchor": (rv["p_market_anchor"] or {}).get(key), "p_final_model": None, "model_status": rv["model_status"],
                             "break_even_odds": break_even(s.get("model_prob") or 0.0), "o_min": o_min(s.get("model_prob") or 0.0, pcfg) if s.get("model_prob") else None}
        for w in r.get("wagers", []):
            w["research"] = gate_wager(w, rv, board, rcfg, pcfg)
    for key in ("pick3", "pick4"):
        rec = ((result.get("multirace") or {}).get(key) or {}).get("recommended")
        if rec:
            rec["research"] = {"decision": "CANDIDATE", "codes": ["UNPRICED_EXOTIC_POOL"], "label": "candidate, unpriced"}
