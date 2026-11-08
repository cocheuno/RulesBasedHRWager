"""
Multi-race (Pick 3 / Pick 4) construction.

Takes the per-race scoresheets produced by engine.score_card and builds
horizontal tickets the way the published experts describe it:

  * grade every live horse in every leg A / B / C (Crist, *Exotic Betting*);
  * single only where there is a genuine standout, spread where the race is
    contentious, and never build a ticket around a horse that may not run;
  * identify vulnerable favourites - the leg where the chalk loses is where a
    Pick 4 pays - and make sure the ticket is alive if they lose;
  * play a main ticket (all A's) plus "A's with one B" backups, then trim to
    the budget by dropping the weakest B's first (Crist's structured tickets
    rather than a "caveman" box);
  * compare candidate sequences by hit probability, number of singles and
    number of price legs, and report the ML parlay as a will-pay yardstick
    (Meadow).

Every decision is made by a registered H-rule whose docstring is the rule
definition (they appear in RULES.md), and every leg carries an audit list
naming the rules that shaped it.  Deterministic: no randomness.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable

from .probability import DEFAULT_PROBABILITY, price_factor, race_probs
from .rules import Rule

HRULES: list[Rule] = []

DEFAULT_MULTIRACE = {
    "pick3": {"base": 1.0, "budget": 60.0},
    "pick4": {"base": 0.50, "budget": 100.0},
    "single_prob": 0.45,        # top horse needs this blended probability ... (H2)
    "single_gap": 7.0,          # ... and this score gap to the 2nd live horse to be a single
    "a_coverage": 0.55,         # A horses cover this much probability (H4)
    "b_coverage": 0.78,         # A+B cover this much
    "max_a": 3, "max_b": 3,
    "chaos_a_coverage": 0.65, "chaos_b_coverage": 0.85, "chaos_max_a": 4, "chaos_max_b": 4,
    "chaos_field": 10,          # a 10+ horse field whose top horse is under chaos_top_prob is a chaos leg (H3)
    "chaos_top_prob": 0.25,
    "spread_gap": 4.0,          # 4+ live horses within this many points of the top => contentious (H3)
    "min_b_prob": 0.06,         # never add a B below this probability (H4)
    "fav_vulnerable_ratio": 0.80,  # favourite is vulnerable when model prob < ML prob * ratio (H5)
    "fav_vulnerable_rules": ["S6", "P2", "V1", "C9", "C10", "F5", "X1", "X4"],  # negative hits that make chalk beatable
    "single_backup": False,     # add the 2nd horse as a B in single legs (a backup ticket)
    "price_leg_bonus": 0.35,    # sequence score multipliers (H9)
    "single_bonus": 0.25,
}


def hrule(id: str, name: str):
    def deco(fn: Callable):
        HRULES.append(Rule(id, name, "horizontal", 0, fn, (fn.__doc__ or "").strip(), False))
        return fn
    return deco


@dataclass
class Leg:
    race_no: int
    sheets: list            # live sheets only (not eliminated, not AE/MTO)
    excluded: list          # AE / MTO alternates
    probs: dict             # pgm -> blended win probability
    model_probs: dict
    ml_probs: dict
    favorite: str | None
    kind: str = "standard"  # single | standard | chaos
    A: list = None
    B: list = None
    price_leg: bool = False
    audit: list = None
    class_text: str = ""
    price_factor: float = 1.0   # share of the win probability left to live horses when pricing tickets


# ---------------------------------------------------------------------------
# H-rules
# ---------------------------------------------------------------------------
@hrule("H1", "Leg win probabilities")
def h1(leg: Leg, cfg: dict):
    """Each live horse's chance in a leg is the engine's one win probability (handicapper/probability.py): the
    softmax of the ability score (scale `probability.logit_scale`) blended with the morning line renormalised over
    the live horses, p = (1 - ml_blend) * model + ml_blend * ML.  The same numbers appear on the race report and the
    screen.  Eliminated horses get 0 here; when a ticket is priced each keeps `elim_floor` (H7 hit probability).
    A leg with a horse that has no morning line uses the model probabilities alone, and says so.
    Basis: Benter (1994) - a handicapping model improves markedly when combined with the public's odds; Crist - grade
    horses by how likely they are to win, not by how much you like them."""
    if all("win_prob" in s for s in leg.sheets):            # computed once by the engine
        leg.model_probs = {s["pgm"]: s["model_prob"] for s in leg.sheets}
        leg.ml_probs = {s["pgm"]: (s["market_prob"] if s.get("market_prob") is not None else s["model_prob"]) for s in leg.sheets}
        leg.probs = {s["pgm"]: s["win_prob"] for s in leg.sheets}
        missing = [s["pgm"] for s in leg.sheets if s.get("ml_decimal") is None]
        lam = 0.0 if missing else cfg.get("probability", DEFAULT_PROBABILITY)["ml_blend"]
    else:                                                    # sheets scored elsewhere: same function, same numbers
        pr = race_probs(leg.sheets, cfg.get("probability"))
        leg.model_probs, leg.probs, lam, missing = pr["model"], pr["win"], pr["blend"], pr["missing"]
        leg.ml_probs = pr["market"] or dict(pr["model"])
    top = max(leg.probs, key=leg.probs.get)
    leg.audit.append(f"H1 win probabilities (model {1 - lam:.0%} / ML {lam:.0%}); top #{top} {leg.probs[top]:.0%}"
                     + (f"; no morning line for #{', #'.join(missing)}: model probabilities only" if missing else ""))


@hrule("H3", "Chaos (spread) leg")
def h3(leg: Leg, cfg: dict):
    """A leg is a chaos leg when 4+ live horses are within `spread_gap` points of the top score, or the field has
    `chaos_field`+ live horses and the top blended probability is under `chaos_top_prob`.  Chaos legs use the wider
    coverage targets and caps (chaos_a_coverage / chaos_b_coverage / chaos_max_a / chaos_max_b).
    Basis: Crist / DRF - spread where your opinion is weakest, single where it is strongest; large contentious fields
    (maiden claimers, turf sprints, hot-pace routes) are where the public's chalk is most beatable."""
    top = leg.sheets[0]["score"]
    within = sum(1 for s in leg.sheets if top - s["score"] <= cfg["spread_gap"])
    ptop = max(leg.probs.values())
    if within >= 4 or (len(leg.sheets) >= cfg["chaos_field"] and ptop < cfg["chaos_top_prob"]):
        leg.kind = "chaos"
        leg.audit.append(f"H3 chaos leg: {within} within {cfg['spread_gap']} pts, {len(leg.sheets)} live, top prob {ptop:.0%}")


@hrule("H2", "Single")
def h2(leg: Leg, cfg: dict):
    """The top horse is a single when its blended probability is >= `single_prob`, its score is >= `single_gap`
    points clear of the next live horse, the leg is not a chaos leg, and it carries none of the vulnerability hits
    listed in `fav_vulnerable_rules`.  A single's leg has only the one A horse (a B backup only if `single_backup`).
    Short-priced singles are still singles: the saving is spent spreading elsewhere.
    Basis: Crist - "a Pick 4 without a single is a lottery ticket"; singling where you have a real opinion is what
    finances the spread in the legs where you do not."""
    if leg.kind == "chaos" or len(leg.sheets) < 2:
        return
    top, second = leg.sheets[0], leg.sheets[1]
    gap = top["score"] - second["score"]
    bad = [h["rule"] for h in top["hits"] if h["points"] < 0 and h["rule"] in cfg["fav_vulnerable_rules"]]
    if leg.probs[top["pgm"]] >= cfg["single_prob"] and gap >= cfg["single_gap"] and not bad:
        leg.kind = "single"
        leg.A = [top["pgm"]]
        leg.B = [second["pgm"]] if cfg["single_backup"] and leg.probs[second["pgm"]] >= cfg["min_b_prob"] else []
        leg.audit.append(f"H2 single #{top['pgm']}: prob {leg.probs[top['pgm']]:.0%}, {gap:.1f} pts clear" +
                         (f" (ML {top['ml_odds']}, short price but the saving buys coverage elsewhere)" if (top["ml_decimal"] or 9) < 1.5 else ""))
    elif leg.probs[top["pgm"]] >= cfg["single_prob"] and gap >= cfg["single_gap"] and bad:
        leg.audit.append(f"H2 #{top['pgm']} would be a single but carries {','.join(bad)}; spread instead")


@hrule("H4", "Coverage grading A / B")
def h4(leg: Leg, cfg: dict):
    """In a non-single leg, horses are taken in probability order: A until the A's cover `a_coverage` of the leg's
    probability (at most `max_a`), then B until A+B cover `b_coverage` (at most `max_b`, never a horse under
    `min_b_prob`).  A leg always carries at least two horses unless it is a single.  Chaos legs use the chaos targets.
    Basis: Crist's A/B/C grading - A's are the horses you expect to win, B's the ones that would not surprise you;
    coverage of win probability, not head-count, decides how deep to go."""
    if leg.kind == "single":
        return
    chaos = leg.kind == "chaos"
    a_t = cfg["chaos_a_coverage" if chaos else "a_coverage"]
    b_t = cfg["chaos_b_coverage" if chaos else "b_coverage"]
    a_max = cfg["chaos_max_a" if chaos else "max_a"]
    b_max = cfg["chaos_max_b" if chaos else "max_b"]
    order = sorted(leg.probs, key=lambda k: (-leg.probs[k], k))
    A, B, cum = [], [], 0.0
    for pgm in order:
        p = leg.probs[pgm]
        if len(A) < a_max and (cum < a_t or len(A) < 2):
            A.append(pgm)
            cum += p
        elif len(B) < b_max and cum < b_t and p >= cfg["min_b_prob"]:
            B.append(pgm)
            cum += p
        else:
            break
    leg.A, leg.B = A, B
    covA = sum(leg.probs[k] for k in A)
    leg.audit.append(f"H4 A={A} ({covA:.0%}) B={B} ({covA + sum(leg.probs[k] for k in B):.0%}) targets {a_t:.0%}/{b_t:.0%}")


@hrule("H5", "Vulnerable favourite")
def h5(leg: Leg, cfg: dict):
    """The ML favourite is vulnerable when it is not the top-scored horse, or when its model probability is below
    `fav_vulnerable_ratio` times its ML probability.  A vulnerable favourite sitting among the A's is demoted to B
    (unless it is the only A); one not on the ticket at all is added as a B when its probability clears
    `min_b_prob`.  The leg is then a "price leg".  A favourite that is still the top-scored horse but carries a
    negative hit from a rule in `fav_vulnerable_rules` (bounce risk, speed duel, underlay, suspicious drop, maiden
    graduate, no-excuse flop) is only noted: it stays an A and H2 has already refused to single it.
    Basis: Davidowitz / DRF - favourites win about a third of races; the Pick 4 pays when the chalk loses in a leg
    where you were alive, so a chalk you are against is kept as a cheap B; Crist - but your own top choice is
    always an A, a warning sign means spread around it, not against it."""
    fav = leg.favorite
    if fav is None or leg.kind == "single" or fav not in leg.probs:
        return
    sheet = next(s for s in leg.sheets if s["pgm"] == fav)
    reasons = []
    if leg.sheets[0]["pgm"] != fav:
        reasons.append(f"ranks {sheet['rank']} by score")
    if leg.model_probs[fav] < cfg["fav_vulnerable_ratio"] * leg.ml_probs[fav]:
        reasons.append(f"model {leg.model_probs[fav]:.0%} vs ML {leg.ml_probs[fav]:.0%}")
    bad = [h["rule"] for h in sheet["hits"] if h["points"] < 0 and h["rule"] in cfg["fav_vulnerable_rules"]]
    if not reasons:
        if bad:
            leg.audit.append(f"H5 favourite #{fav} ({sheet['ml_odds']}) is the top pick but carries {','.join(bad)}: stays A, not singled, spread around it")
        else:
            leg.audit.append(f"H5 favourite #{fav} ({sheet['ml_odds']}) looks legitimate")
        return
    if bad:
        reasons.append("hits " + ",".join(bad))
    leg.price_leg = True
    if fav in leg.A and len(leg.A) > 1:
        leg.A.remove(fav)
        leg.B.insert(0, fav)
        act = "demoted to B"
    elif fav in leg.A:
        act = "kept as the lone A (nothing else to prefer)"
    elif fav in leg.B:
        act = "stays B"
    elif leg.probs[fav] >= cfg["min_b_prob"]:
        leg.B.append(fav)
        act = "added as B for insurance"
    else:
        act = "left off"
    leg.audit.append(f"H5 vulnerable favourite #{fav} ({sheet['ml_odds']}): " + "; ".join(reasons) + f" -> {act}; price leg")


@hrule("H6", "Also-eligibles and throw-outs")
def h6(leg: Leg, cfg: dict):
    """Horses eliminated by an X rule are never on a ticket.  Also-eligible / main-track-only horses are never on a
    ticket either; if one would have graded A or B it is reported as an alternate to add if it draws in.
    Basis: Crist - a ticket built around a horse that may not run is a refund at best and a dead ticket at worst."""
    for s in leg.excluded:
        if s["rank"] <= 3:
            leg.audit.append(f"H6 #{s['pgm']} {s['name']} is {'/'.join(s['flags'])} (rank {s['rank']}): add if it draws in")


def _rules_for_leg(leg: Leg, cfg: dict):
    for rid in ("H1", "H3", "H2", "H4", "H5", "H6"):
        next(r for r in HRULES if r.id == rid).fn(leg, cfg)


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------
@hrule("H7", "Main ticket plus one-B backups")
def h7(seq: dict, cfg: dict):
    """The main ticket uses every A in every leg.  For each leg that has B horses, one backup ticket uses that leg's
    B's with the A's everywhere else ("A's with one B").  Two legs' B's never appear on the same ticket.
    Basis: Crist's structured tickets - most of the money goes where the opinion is; backups protect against one
    upset, not two, which is what keeps the cost proportional to the chance of cashing."""
    legs = seq["legs"]
    tickets = [{"name": "main (all A)", "legs": [list(l.A) for l in legs]}]
    for i, l in enumerate(legs):
        if l.B:
            tickets.append({"name": f"backup: B in R{l.race_no}", "legs": [list(l.B) if j == i else list(x.A) for j, x in enumerate(legs)]})
    seq["tickets"] = tickets


@hrule("H8", "Budget trim")
def h8(seq: dict, cfg: dict):
    """While the sequence costs more than the budget, remove the lowest-probability B from the leg with the most B's;
    when no B is left, remove the lowest-probability A from the leg with the most A's (a leg never drops below one
    horse, and a single is never touched).  Each removal is recorded.
    Basis: Crist / Meadow - the budget is set first; the ticket is shaped to it by cutting the marginal horses, not
    by shrinking the opinion."""
    base = seq["base"]
    budget = seq["budget"]
    legs = seq["legs"]

    def cost():
        return sum(math.prod(len(x) for x in t["legs"]) for t in seq["tickets"]) * base

    seq["cost_before_trim"] = cost()
    while cost() > budget:
        cands = [l for l in legs if l.B]
        if cands:
            l = max(cands, key=lambda l: (len(l.B), -l.race_no))
            victim = min(l.B, key=lambda k: l.probs[k])
            l.B.remove(victim)
            seq["notes"].append(f"H8 over budget ${cost():.2f} > ${budget:.2f}: dropped B #{victim} from R{l.race_no}")
        else:
            cands = [l for l in legs if len(l.A) > 1 and l.kind != "single"]
            if not cands:
                seq["notes"].append(f"H8 cannot reach budget ${budget:.2f}; minimum structure costs ${cost():.2f}")
                break
            l = max(cands, key=lambda l: (len(l.A), -l.race_no))
            victim = min(l.A, key=lambda k: l.probs[k])
            l.A.remove(victim)
            seq["notes"].append(f"H8 over budget ${cost():.2f}: dropped A #{victim} from R{l.race_no}")
        h7(seq, cfg)
    seq["cost"] = round(cost(), 2)


@hrule("H9", "Sequence ranking")
def h9(seq: dict, cfg: dict):
    """Hit probability = P(all A's win) + sum over legs of P(that leg's B wins and every other leg's A wins), using the
    H1 probabilities scaled by the leg's pricing factor (each eliminated horse keeps `elim_floor`, pricing only).  Sequence score = hit probability x (1 + single_bonus x singles) x (1 + price_leg_bonus x price
    legs).  The ML parlay of the lowest-priced A in each leg is reported as a conservative will-pay yardstick, and
    the probability that every leg's favourite wins is reported as the "chalk" risk.
    Basis: Crist - prefer sequences where you have at least one strong opinion and at least one beatable favourite;
    Meadow - a multi-race bet has to beat the parlay of its parts to be worth the extra takeout."""
    legs = seq["legs"]
    PA = [l.price_factor * sum(l.probs[k] for k in l.A) for l in legs]
    PB = [l.price_factor * sum(l.probs[k] for k in l.B) for l in legs]
    hit = math.prod(PA)
    for i in range(len(legs)):
        hit += PB[i] * math.prod(PA[j] for j in range(len(legs)) if j != i)
    seq["hit_prob"] = round(hit, 4)
    seq["singles"] = sum(1 for l in legs if l.kind == "single")
    seq["price_legs"] = sum(1 for l in legs if l.price_leg)
    seq["score"] = round(hit * (1 + cfg["single_bonus"] * seq["singles"]) * (1 + cfg["price_leg_bonus"] * seq["price_legs"]), 4)
    parlay = 1.0
    chalk = 1.0
    for l in legs:
        mls = [next(s["ml_decimal"] for s in l.sheets if s["pgm"] == k) for k in l.A]
        mls = [m for m in mls if m is not None]
        parlay *= (1 + min(mls)) if mls else 1.0
        chalk *= l.probs.get(l.favorite, 0.0) if l.favorite else 1.0
    seq["ml_parlay"] = round(parlay * seq["base"], 2)
    seq["all_favorites_prob"] = round(chalk, 4)


@hrule("H10", "Offered windows and denominations")
def h10(result: dict, cfg: dict) -> dict:
    """The Ultimate PP header lists the wagers offered on each race ("50c Rolling Pick 3", "50c Early Pick 4",
    "$3 Late Pick 3", "$.50 Pick 4 (Races 8-9-10-11)", "$1.00 Bet 3 (Races 6-7-8)").  A Pick 3 / Pick 4 window is
    built only when the menu of its first race offers it; "Rolling" means a window starting at that race,
    "Early"/"Late" likewise, an explicit race list is taken as written (consecutive races only).  The ticket is
    priced at the configured denomination (pick3/pick4 `base`: $1 and $0.50) unless the menu's minimum is higher
    (a "$3 Late Pick 3" is bet at $3).  When a card's menu names no Pick 3 / Pick 4 at all, every consecutive
    window is built at the configured base.
    Basis: a ticket you cannot buy is not a bet; Crist - know the menu and its minimums before building."""
    offered = {"pick3": {}, "pick4": {}}
    for r in result["races"]:
        txt = r.get("wagers_menu") or ""
        for m in re.finditer(r"(?P<amt>\$\s?\d*\.?\d+|\d+\s?c)\s*(?:(?P<kind>Rolling|Early|Late|Turf)\s+)?(?:Pick\s*|Bet\s*)(?P<n>[34])\b\s*(?:\((?:Races?\s*)?(?P<list>[\dR\-\s]+)\))?", txt, re.I):
            amt = m.group("amt").replace(" ", "")
            base = float(amt[1:]) if amt.startswith("$") else float(amt[:-1]) / 100.0
            n = int(m.group("n"))
            key = f"pick{n}"
            if m.group("list"):
                nums = [int(x) for x in re.findall(r"\d+", m.group("list"))]
                if len(nums) == n and nums == list(range(nums[0], nums[0] + n)):
                    offered[key][nums[0]] = base
                continue   # explicit non-consecutive list (e.g. Turf Pick 3 R4-6-8): not built
            offered[key][r["race_no"]] = base
    return offered


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def make_leg(r: dict, cfg: dict) -> Leg | None:
    live = [s for s in r["sheets"] if not s["eliminated"] and not s["flags"]]
    excluded = [s for s in r["sheets"] if not s["eliminated"] and s["flags"]]
    if not live:
        return None
    mls = [(s["ml_decimal"], s["pgm"]) for s in live if s["ml_decimal"] is not None]
    n_elim = sum(1 for s in r["sheets"] if s["eliminated"])
    leg = Leg(race_no=r["race_no"], sheets=live, excluded=excluded, probs={}, model_probs={}, ml_probs={},
              favorite=min(mls)[1] if mls else None, A=[], B=[], audit=[], class_text=r.get("class_text") or "",
              price_factor=price_factor(n_elim, cfg.get("probability")))
    if n_elim:
        leg.audit.append(f"pricing keeps {cfg.get('probability', DEFAULT_PROBABILITY)['elim_floor']:.0%} for each of the "
                         f"{n_elim} eliminated horse(s): live probabilities x {leg.price_factor:.2f} in the hit probability only")
    _rules_for_leg(leg, cfg)
    return leg


def build_sequence(result: dict, start_idx: int, n: int, cfg: dict, name: str, base: float | None = None) -> dict | None:
    races = result["races"][start_idx:start_idx + n]
    if len(races) < n:
        return None
    legs = [make_leg(r, cfg) for r in races]
    if any(l is None for l in legs):
        return None
    key = "pick3" if n == 3 else "pick4"
    seq = {"name": name, "races": [r["race_no"] for r in races], "legs": legs, "base": base if base is not None else cfg[key]["base"],
           "budget": cfg[key]["budget"], "notes": []}
    h7(seq, cfg)
    h8(seq, cfg)
    h9(seq, cfg)
    return seq


def leg_summary(r: dict, cfg: dict) -> dict | None:
    """Grade one race as a leg (H1-H6) without building tickets; used for the per-race wager suggestions."""
    leg = make_leg(r, cfg)
    if leg is None:
        return None
    return {"kind": leg.kind, "A": leg.A, "B": leg.B, "favorite": leg.favorite, "price_leg": leg.price_leg,
            "probs": leg.probs, "price_factor": leg.price_factor, "audit": leg.audit}


def build_all(result: dict, cfg: dict) -> dict:
    """All consecutive Pick 3 and Pick 4 windows on the card, ranked; `recommended` is the best window of each."""
    out = {}
    offered = h10(result, cfg)
    for n, key, label in ((3, "pick3", "Pick 3"), (4, "pick4", "Pick 4")):
        seqs = []
        menu = offered[key]
        for i in range(0, len(result["races"]) - n + 1):
            start = result["races"][i]["race_no"]
            if menu and start not in menu:
                continue
            minimum = menu.get(start) if menu else None
            base = max(minimum, cfg[key]["base"]) if minimum is not None else None
            s = build_sequence(result, i, n, cfg, f"{label} R{start}-R{result['races'][i + n - 1]['race_no']}", base)
            if s:
                if menu:
                    s["notes"].insert(0, f"H10 offered on the R{start} menu (minimum ${minimum:.2f}); bet at ${base:.2f}")
                seqs.append(s)
        seqs.sort(key=lambda s: (-s["score"], s["races"][0]))
        out[key] = {"label": label, "offered": {str(k): v for k, v in menu.items()}, "windows": [_serialize(s) for s in seqs],
                    "recommended": _serialize(seqs[0]) if seqs else None}
    return out


def _serialize(seq: dict) -> dict:
    return {
        "name": seq["name"], "races": seq["races"], "base": seq["base"], "budget": seq["budget"],
        "cost": seq["cost"], "cost_before_trim": round(seq["cost_before_trim"], 2), "hit_prob": seq["hit_prob"],
        "score": seq["score"], "singles": seq["singles"], "price_legs": seq["price_legs"],
        "ml_parlay": seq["ml_parlay"], "all_favorites_prob": seq["all_favorites_prob"], "notes": seq["notes"],
        "tickets": [{"name": t["name"], "legs": t["legs"], "combos": math.prod(len(x) for x in t["legs"]),
                     "cost": round(math.prod(len(x) for x in t["legs"]) * seq["base"], 2)} for t in seq["tickets"]],
        "legs": [{"race_no": l.race_no, "class_text": l.class_text, "kind": l.kind, "A": l.A, "B": l.B, "favorite": l.favorite,
                  "price_leg": l.price_leg, "probs": l.probs, "price_factor": l.price_factor, "audit": l.audit} for l in seq["legs"]],
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def format_multirace(mr: dict, result: dict, detail: int = 1) -> str:
    names = {r["race_no"]: {s["pgm"]: s for s in r["sheets"]} for r in result["races"]}
    L = ["## Multi-race wagers (Pick 3 / Pick 4)", ""]
    for key in ("pick3", "pick4"):
        blk = mr.get(key)
        if not blk or not blk["recommended"]:
            L.append(f"*{key}: not enough races on the card*")
            L.append("")
            continue
        rec = blk["recommended"]
        L.append(f"### {rec['name']}  — cost ${rec['cost']:.2f} (base ${rec['base']:.2f}, budget ${rec['budget']:.0f}), "
                 f"hit probability {rec['hit_prob']:.0%}, {rec['singles']} single(s), {rec['price_legs']} price leg(s)")
        L.append(f"ML parlay of the shortest A's ${rec['ml_parlay']:.2f}; chance every favourite wins {rec['all_favorites_prob']:.0%}")
        L.append("")
        L.append("| Leg | Race | Type | A | B | Fav | Notes |")
        L.append("|---|---|---|---|---|---|---|")
        for i, l in enumerate(rec["legs"], 1):
            fmt = lambda ks: ", ".join(f"#{k} {names[l['race_no']][k]['name']} ({l['probs'][k]:.0%})" for k in ks) or "—"
            note = "price leg" if l["price_leg"] else ""
            L.append(f"| {i} | R{l['race_no']} {l['class_text']} | {l['kind']} | {fmt(l['A'])} | {fmt(l['B'])} | #{l['favorite']} | {note} |")
        L.append("")
        L.append("Tickets:")
        for t in rec["tickets"]:
            L.append(f"- {t['name']}: " + " / ".join(",".join(x) for x in t["legs"]) + f"  = {t['combos']} combos, ${t['cost']:.2f}")
        for n in rec["notes"]:
            L.append(f"- {n}")
        if detail >= 2:
            L.append("")
            L.append("Audit:")
            for l in rec["legs"]:
                for a in l["audit"]:
                    L.append(f"- R{l['race_no']}: {a}")
        if len(blk["windows"]) > 1:
            L.append("")
            L.append("| Window | Cost | Hit prob | Singles | Price legs | Score |")
            L.append("|---|---|---|---|---|---|")
            for w in blk["windows"]:
                L.append(f"| {w['name']} | ${w['cost']:.2f} | {w['hit_prob']:.0%} | {w['singles']} | {w['price_legs']} | {w['score']:.3f} |")
        L.append("")
    return "\n".join(L)
