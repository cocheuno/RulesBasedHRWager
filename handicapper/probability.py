"""
One probability for the whole engine.

Every screen and ticket reads the same numbers, computed once per race over the *live* horses (not eliminated,
not an also-eligible / main-track-only alternate):

  model_prob   softmax of the ability score (points per e-fold = `logit_scale`): the engine's own opinion;
  market_prob  the morning line renormalised over the same horses (1/(ML+1)); None when any live horse has no ML;
  win_prob     the blend  (1 - ml_blend) * model + ml_blend * market  (Benter 1994: a model improves when it is
               combined with the public's line); equals model_prob when the market is unknown.

Fair odds and the value assessment (rule V1) come from model_prob only - value is model against market, so the
market cannot be inside the number it is compared with.  Eliminated horses have probability 0 for selection and
grading (the X rules are hard, by design).  Only when a Pick 3 / Pick 4 ticket is *priced* does each eliminated
horse keep `elim_floor` (2%) - an upset by an eliminated horse is rare, not impossible, and the hit probability
should say so.  That factor never touches the picks.
"""
from __future__ import annotations

import math

DEFAULT_PROBABILITY = {
    "logit_scale": 18.0,   # points per e-fold in model probability (was 12 for V1 and 18 for the legs)
    "ml_blend": 0.35,      # weight of the morning line in win_prob
    "elim_floor": 0.02,    # per eliminated horse, in ticket pricing only
}


def softmax(scores: dict[str, float], scale: float) -> dict[str, float]:
    """p_i = exp(s_i / scale) / sum_j exp(s_j / scale)."""
    if not scores:
        return {}
    m = max(scores.values())
    ex = {k: math.exp((v - m) / scale) for k, v in scores.items()}
    z = sum(ex.values())
    return {k: v / z for k, v in ex.items()}


def market(mls: dict[str, float | None]) -> dict[str, float] | None:
    """Morning-line probabilities renormalised to 1 (takes the overround out); None when any price is missing."""
    if not mls or any(v is None for v in mls.values()):
        return None
    raw = {k: 1.0 / (v + 1.0) for k, v in mls.items()}
    z = sum(raw.values())
    return {k: v / z for k, v in raw.items()}


def fair_odds(p: float) -> float | None:
    return round((1 - p) / p, 1) if p > 0.001 else None


def race_probs(live: list[dict], cfg: dict | None = None) -> dict:
    """live: the sheets that can win (score, pgm, ml_decimal).  Returns {model, market, win, blend, missing}."""
    cfg = dict(DEFAULT_PROBABILITY, **(cfg or {}))
    scores = {s["pgm"]: s["score"] for s in live}
    model = softmax(scores, cfg["logit_scale"])
    mkt = market({s["pgm"]: s.get("ml_decimal") for s in live})
    missing = [s["pgm"] for s in live if s.get("ml_decimal") is None]
    lam = cfg["ml_blend"] if mkt is not None else 0.0
    win = {k: round((1 - lam) * model[k] + lam * (mkt[k] if mkt else 0.0), 4) for k in scores}
    return {"model": {k: round(v, 4) for k, v in model.items()}, "market": mkt and {k: round(v, 4) for k, v in mkt.items()},
            "win": win, "blend": lam, "missing": missing}


def price_factor(n_eliminated: int, cfg: dict | None = None) -> float:
    """Share of the win probability left to the live horses when each eliminated horse keeps elim_floor (pricing only)."""
    cfg = dict(DEFAULT_PROBABILITY, **(cfg or {}))
    return max(0.5, 1.0 - n_eliminated * cfg["elim_floor"])
