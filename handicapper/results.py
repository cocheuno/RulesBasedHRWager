"""
Race results, scratches and same-day bias.

Results file (results/<card>.results.json), transcribed from the track's
payout / finish-order pages:

{
  "track": "Del Mar", "date": "2026-11-06",
  "races": [
    {"race_no": 1,
     "finish": ["1", "6", "4", "3"],                 # program numbers, 1st .. nth (as many as known)
     "win": 5.20, "place": {"1": 3.40, "6": 9.20}, "show": {"1": 2.10, "6": 3.20, "4": 2.10},   # $2 payoffs
     "exotics": [{"type": "EXACTA", "base": 1.0, "combo": "1/6", "payout": 17.30}, ...],
     "final_odds": {"1": 1.6, "6": 9.4}             # optional, decimal odds-to-1 when the chart shows them
    }
  ]
}

Scratch spec (pick.py --scratch): "3:3, 4:6, 8:4, 8:9"  -> race 3 program 3, race 4 program 6, race 8 programs 4 and 9.
"""
from __future__ import annotations

import json
import re

EARLY = ("E", "E/P")
LATE = ("P", "S")


def _norm_track(name) -> str:
    return re.sub(r"[^a-z]", "", str(name or "").lower())


def check_identity(card_or_picks: dict, results: dict) -> str:
    """Results must belong to the card they are joined with.  The results file's track and date (top level, and
    a chart's own track name on each race) are compared with the card's track name / code and date.  Returns
    "verified" when they match, "unverified" when the results carry no track or date; raises ValueError on a
    conflict, so a wrong-day or wrong-track file can never produce a back-test, a bias or a return."""
    c_track, c_code, c_date = card_or_picks.get("track"), card_or_picks.get("track_code"), card_or_picks.get("date")
    problems = []
    r_track, r_date = results.get("track"), results.get("date")
    if r_date and c_date and str(c_date) != str(r_date):
        problems.append(f"date {r_date} vs card {c_date}")
    if r_track and c_track and _norm_track(c_track) != _norm_track(r_track) and _norm_track(c_code) != _norm_track(r_track):
        problems.append(f"track {r_track!r} vs card {c_track!r}")
    names = _card_names(card_or_picks)
    for r in results.get("races", []):
        t = r.get("track")
        if t and c_track and _norm_track(t) != _norm_track(c_track) and _norm_track(c_code) != _norm_track(t):
            problems.append(f"R{r.get('race_no')} chart is from {t!r}, card is {c_track!r}")
        if r.get("date") and c_date and str(r["date"]) != str(c_date):
            problems.append(f"R{r.get('race_no')} chart is dated {r['date']}, card is {c_date}")
        ran = [u.get("name") for u in r.get("runners") or [] if u.get("name")]
        mine = names.get(r.get("race_no"))
        if mine and len(ran) >= 3:
            hits = sum(1 for n in ran if _same_horse(n, mine))
            if hits * 2 < len(ran):
                problems.append(f"R{r.get('race_no')} chart's horses ({', '.join(ran[:3])} ...) are not this card's race {r.get('race_no')} "
                                f"({hits} of {len(ran)} names match)")
    if problems:
        raise ValueError("results do not belong to this card: " + "; ".join(problems))
    return "verified" if (r_track and r_date) else "unverified"


def _card_names(card_or_picks: dict) -> dict:
    """{race_no: set of normalised horse names} from a card (horses) or a picks document (sheets)."""
    from .identity import norm_name
    out = {}
    for r in card_or_picks.get("races", []) or []:
        rows = r.get("horses") or r.get("sheets") or []
        names = {norm_name(h.get("name")) for h in rows if h.get("name")}
        if names:
            out[r.get("race_no")] = names
    return out


def _same_horse(name: str, names: set) -> bool:
    from .identity import norm_name
    n = norm_name(name)
    if not n:
        return False
    if n in names:
        return True
    first = n.split()[0]
    return any(x.split()[:1] == [first] and (len(first) > 3 or x.startswith(n[:8])) for x in names)


def winners_of(res: dict | None) -> list[str]:
    """The race's winners: one, or more after a dead heat for the win (the chart's "winners")."""
    if not res:
        return []
    w = res.get("winners")
    return [str(x) for x in w] if w else [str(x) for x in (res.get("finish") or [])[:1]]


def win_price_of(res: dict | None, pgm: str) -> float | None:
    """The $2 win price this horse paid: its own price after a dead heat, else the race's win price for the winner."""
    if not res:
        return None
    wb = res.get("win_by") or {}
    if str(pgm) in wb:
        return wb[str(pgm)]
    return res.get("win") if winners_of(res)[:1] == [str(pgm)] else None


def load_results(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        res = json.load(fh)
    for r in res.get("races", []):
        r["finish"] = [str(p) for p in r.get("finish", [])]
        if r.get("winners"):
            r["winners"] = [str(p) for p in r["winners"]]
    return res


# ---------------------------------------------------------------------------
# Scratches
# ---------------------------------------------------------------------------
def parse_scratch_spec(spec: str | None) -> dict[int, list[str]]:
    """'3:3, 4:6 8:4,8:9' -> {3: ['3'], 4: ['6'], 8: ['4', '9']}.  Two extra forms state the official draw-in
    status instead of leaving it to the automatic rule: '4:+12' = also-eligible / MTO #12 is officially in;
    '4:-12' = #12 stays out even though a scratch would normally bring it in."""
    out: dict[int, list[str]] = {}
    for tok in re.split(r"[,\s]+", (spec or "").strip()):
        if not tok:
            continue
        m = re.fullmatch(r"(\d+):([+-]?)(\d+[A-Za-z]?)", tok)
        if not m:
            raise ValueError(f"bad scratch token {tok!r}; expected race:program like 8:4 (8:+4 draws in, 8:-4 stays out)")
        out.setdefault(int(m.group(1)), []).append(m.group(2) + m.group(3).upper())
    return out


def apply_scratches(card: dict, scratches: dict[int, list[str]]) -> list[str]:
    """Remove scratched horses from the card in place.  For every scratch in a race, the lowest-numbered
    also-eligible (AE) in that race draws in (its entry_status is cleared) - the track's draw-in order.
    Main-track-only (MTO) horses are left flagged: they run only if the race comes off the turf.
    Returns human-readable notes."""
    notes = []
    for race in card["races"]:
        toks = scratches.get(race["race_no"], [])
        if not toks:
            continue
        pg = [t for t in toks if t[0] not in "+-"]
        force_in = [t[1:] for t in toks if t[0] == "+"]
        hold_out = [t[1:] for t in toks if t[0] == "-"]
        before = len(race["horses"])
        gone = [h for h in race["horses"] if h["pgm"].upper() in pg]
        race["horses"] = [h for h in race["horses"] if h["pgm"].upper() not in pg]
        missing = [p for p in pg if p not in {h["pgm"].upper() for h in gone}]
        for p in missing:
            notes.append(f"R{race['race_no']}: program {p} not found (already absent?)")
        for h in gone:
            notes.append(f"R{race['race_no']}: scratched #{h['pgm']} {h['name']}")
        # official status first: '+p' is in whatever the count says, '-p' never draws in automatically
        for h in race["horses"]:
            if h["pgm"].upper() in force_in and h.get("entry_status"):
                notes.append(f"R{race['race_no']}: #{h['pgm']} {h['name']} officially in ({h['entry_status']} activated)")
                h["entry_status"] = None
        for p in force_in:
            if p not in {h["pgm"].upper() for h in race["horses"]}:
                notes.append(f"R{race['race_no']}: program {p} not found for draw-in")
        body_scratches = sum(1 for h in gone if h.get("entry_status") != "AE")   # a scratched AE draws nobody in
        body_scratches -= sum(1 for h in race["horses"] if h["pgm"].upper() in force_in)   # an official draw-in uses a slot
        aes = sorted((h for h in race["horses"] if h.get("entry_status") == "AE" and h["pgm"].upper() not in hold_out),
                     key=lambda h: _pgm_key(h["pgm"]))
        for h in aes[:max(0, body_scratches)]:
            h["entry_status"] = None
            notes.append(f"R{race['race_no']}: #{h['pgm']} {h['name']} draws in from the also-eligible list")
        for h in race["horses"]:
            if h["pgm"].upper() in hold_out and h.get("entry_status"):
                notes.append(f"R{race['race_no']}: #{h['pgm']} {h['name']} held out ({h['entry_status']} stays on the list)")
        race["field_size"] = len(race["horses"])
        if race.get("summary"):
            race["summary"] = [e for e in race["summary"] if str(e.get("pgm", "")).upper() not in pg]
        if before and not race["horses"]:
            notes.append(f"R{race['race_no']}: no horses left")
    return notes


def _pgm_key(p: str):
    m = re.match(r"(\d+)([A-Za-z]?)", p)
    return (int(m.group(1)), m.group(2)) if m else (999, p)


# ---------------------------------------------------------------------------
# Same-day bias from the results of earlier races on the card
# ---------------------------------------------------------------------------
def attach_day_bias(card: dict, results: dict) -> list[str]:
    """For each race, summarise the winners of the *earlier* races on the same surface today: how many were
    early types (E, E/P) vs late (P, S), and how many came from inside (post 1-3) / middle / outside (8+) posts.
    Stored as race['day_bias'] and read by rule P10.  Needs the winner's run style and post, which are looked
    up in the card itself (the winner must be among the parsed horses)."""
    by_no = {r["race_no"]: r for r in results.get("races", [])}
    done = []
    notes = []
    if check_identity(card, results) == "unverified":
        notes.append("results file carries no track/date: identity unverified")
    for race in card["races"]:
        same = [d for d in done if d["surface"] == race["surface"]]
        race["day_bias"] = {
            "n": len(same),
            "early_wins": sum(1 for d in same if d["run_style"] in EARLY),
            "late_wins": sum(1 for d in same if d["run_style"] in LATE),
            "inside_wins": sum(1 for d in same if d["post"] is not None and d["post"] <= 3),
            "outside_wins": sum(1 for d in same if d["post"] is not None and d["post"] >= 8),
            "winners": [f"R{d['race_no']} #{d['pgm']} {d['run_style']} post {d['post']}" for d in same],
        }
        res = by_no.get(race["race_no"])
        if res and res.get("finish"):
            wpgm = res["finish"][0]
            w = next((h for h in race["horses"] if h["pgm"].upper() == wpgm.upper()), None)
            if w:
                done.append({"race_no": race["race_no"], "surface": race["surface"], "pgm": wpgm,
                             "run_style": w.get("run_style"), "post": w.get("post")})
            else:
                notes.append(f"R{race['race_no']}: winner #{wpgm} not among parsed horses; not used for day bias")
    return notes


# ---------------------------------------------------------------------------
# Back-test join
# ---------------------------------------------------------------------------
def backtest(picks: dict, results: dict, stake: float = 2.0) -> dict:
    """Join a picks.json with a results file.  Reports, per race, where the winner was ranked, whether the
    primary play won and what a flat win bet on the top pick returned, whether the top three covered the
    winner; per rule, how often a horse that triggered it positively / negatively won; and whether the
    recommended Pick 3 / Pick 4 tickets would have hit (payoff only if the results file carries it)."""
    identity = check_identity(picks, results)
    by_no = {r["race_no"]: r for r in results.get("races", [])}
    races_out, rule_stats, angle_stats = [], {}, {}
    bet, ret = 0.0, 0.0
    for r in picks["races"]:
        res = by_no.get(r["race_no"])
        if not res or not res.get("finish"):
            continue
        wins = winners_of(res)                       # more than one after a dead heat for the win
        win = wins[0]
        sheets = {s["pgm"]: s for s in r["sheets"]}
        ranked = [sheets[w] for w in wins if w in sheets]
        wsheet = min(ranked, key=lambda s: (s["rank"] is None, s["rank"] or 99)) if ranked else None
        live = [s for s in r["sheets"] if not s["eliminated"] and not s["flags"]]
        top = live[0]["pgm"] if live else None
        bn = r.get("brisnet") or {}
        row = {"race_no": r["race_no"], "winner": win, "winners": wins, "dead_heat": len(wins) > 1,
               "winner_rank": wsheet["rank"] if wsheet else None,
               "winner_eliminated": bool(wsheet and wsheet["eliminated"]), "top_pick": top,
               "top_pick_won": top in wins, "winner_in_top3": any(w in [s["pgm"] for s in live[:3]] for w in wins),
               "picks_hit": any(w in r["picks"] for w in wins), "win_payoff": win_price_of(res, top) if top in wins else res.get("win"),
               "brisnet_pick": bn.get("top_pick"), "brisnet_won": bool(bn.get("top_pick")) and bn.get("top_pick") in wins,
               "brisnet_top3": any(w in (bn.get("top3") or []) for w in wins), "brisnet_best_bet": bn.get("best_bet")}
        rd = r.get("racing_dudes") or {}
        rd_order = rd.get("order") or []
        row["rd_pick"] = rd_order[0] if rd_order else None
        row["rd_won"] = bool(rd_order) and rd_order[0] in wins
        row["rd_top4"] = bool(rd_order) and any(w in rd_order for w in wins)
        row["rd_likely_winner"] = bool(rd.get("likely_winner"))
        tf = r.get("timeform") or {}
        tf_rank = tf.get("rank") or {}
        tf_top = [p for p, k in tf_rank.items() if k == 1]
        row["timeform_top"] = tf_top[0] if len(tf_top) == 1 else None
        row["timeform_won"] = bool(row["timeform_top"]) and row["timeform_top"] in wins
        row["timeform_winner_rank"] = min((tf_rank[w] for w in wins if tf_rank.get(w) is not None), default=None)
        row["timeform_power_pick"] = (tf.get("power_picks") or [None])[0]
        row["timeform_power_pick_won"] = bool(row["timeform_power_pick"]) and row["timeform_power_pick"] in wins
        if top:
            bet += stake
            if top in wins and win_price_of(res, top):
                ret += win_price_of(res, top) * stake / 2.0
        races_out.append(row)
        for s in r["sheets"]:
            for h in s["hits"]:
                if not h["points"]:
                    continue
                k = (h["rule"], "pos" if h["points"] > 0 else "neg")
                st = rule_stats.setdefault(k, {"rule": h["rule"], "sign": k[1], "fired": 0, "won": 0, "itm": 0})
                st["fired"] += 1
                st["won"] += int(s["pgm"] in wins)
                st["itm"] += int(s["pgm"] in res["finish"][:3])
            sh = s.get("sheet") or {}
            labels = [("angle", a["label"]) for a in sh.get("angles") or []]
            labels += [("rank", f"{k} #1") for k, v in (sh.get("ranks") or {}).items() if v == 1]
            if sh.get("top_pick"):
                labels.append(("rank", "top pick"))
            if sh.get("best_bet"):
                labels.append(("rank", "best bet"))
            labels += [(a["kind"], a["label"]) for a in s.get("angles") or []]
            rdh = s.get("racing_dudes") or {}
            if rdh.get("role"):
                labels.append(("racing_dudes", f"{rdh['role']} pick"))
                if rdh.get("role") == "Win" and (r.get("racing_dudes") or {}).get("likely_winner"):
                    labels.append(("racing_dudes", "Likely Winner"))
            tfh = s.get("timeform") or {}
            if tfh.get("rank") == 1:
                labels.append(("timeform", "Top Fig #1"))
            if tfh.get("style"):
                labels.append(("timeform", f"style {tfh['style']}"))
            for kind, label in labels:
                st = angle_stats.setdefault((kind, label), {"kind": kind, "label": label, "fired": 0, "won": 0, "itm": 0})
                st["fired"] += 1
                st["won"] += int(s["pgm"] in wins)
                st["itm"] += int(s["pgm"] in res["finish"][:3])
    multi = {}
    for key in ("pick3", "pick4"):
        rec = ((picks.get("multirace") or {}).get(key) or {}).get("recommended")
        if not rec:
            continue
        legw = [winners_of(by_no.get(n)) for n in rec["races"]]
        if any(not w for w in legw):
            multi[key] = {"name": rec["name"], "known": False}
            continue
        winners = [w[0] for w in legw]
        hit = any(all(set(w) & set(leg) for w, leg in zip(legw, t["legs"])) for t in rec["tickets"])
        multi[key] = {"name": rec["name"], "known": True, "winners": winners, "hit": hit, "cost": rec["cost"]}
    rules = sorted(rule_stats.values(), key=lambda x: (x["rule"], x["sign"]))
    angles = sorted(angle_stats.values(), key=lambda x: (x["kind"], -x["fired"], x["label"]))
    for st in rules + angles:
        st["win_pct"] = round(100.0 * st["won"] / st["fired"], 1)
        st["itm_pct"] = round(100.0 * st["itm"] / st["fired"], 1)
    n = len(races_out)
    bench = [r for r in races_out if r["brisnet_pick"]]
    tfb = [r for r in races_out if r.get("timeform_top")]
    rdb = [r for r in races_out if r.get("rd_pick")]
    return {"races": races_out, "rules": rules, "angles": angles, "multirace": multi, "identity": identity,
            "summary": {"races": n, "top_pick_wins": sum(r["top_pick_won"] for r in races_out),
                        "winner_in_top3": sum(r["winner_in_top3"] for r in races_out),
                        "brisnet_races": len(bench), "brisnet_pick_wins": sum(r["brisnet_won"] for r in bench),
                        "brisnet_top3": sum(r["brisnet_top3"] for r in bench),
                        "brisnet_best_bets": sum(1 for r in bench if r["brisnet_best_bet"]),
                        "brisnet_best_bet_wins": sum(1 for r in bench if r["brisnet_best_bet"] and r["brisnet_best_bet"] == r["winner"]),
                        "winner_eliminated": sum(r["winner_eliminated"] for r in races_out),
                        "rd_races": len(rdb), "rd_pick_wins": sum(r["rd_won"] for r in rdb), "rd_top4": sum(r["rd_top4"] for r in rdb),
                        "rd_engine_wins": sum(r["top_pick_won"] for r in rdb),
                        "rd_likely_winner": sum(1 for r in rdb if r["rd_likely_winner"]), "rd_likely_winner_wins": sum(1 for r in rdb if r["rd_likely_winner"] and r["rd_won"]),
                        "timeform_races": len(tfb), "timeform_top_wins": sum(r["timeform_won"] for r in tfb),
                        "timeform_winner_in_top3": sum(1 for r in tfb if (r.get("timeform_winner_rank") or 99) <= 3),
                        "timeform_power_pick_wins": sum(r["timeform_power_pick_won"] for r in races_out if r.get("timeform_power_pick")),
                        "timeform_power_picks": sum(1 for r in races_out if r.get("timeform_power_pick")),
                        "flat_win_bet": round(bet, 2), "flat_win_return": round(ret, 2),
                        "flat_win_roi": round((ret - bet) / bet, 3) if bet else None}}


def format_backtest(bt: dict) -> str:
    s = bt["summary"]
    L = [f"# Back-test: {s['races']} races", ""]
    L.append(f"Top pick won {s['top_pick_wins']}/{s['races']}; winner in top 3: {s['winner_in_top3']}/{s['races']}; "
             f"winner had been eliminated: {s['winner_eliminated']}; flat ${2:.0f} win on the top pick: bet ${s['flat_win_bet']:.2f}, "
             f"returned ${s['flat_win_return']:.2f}" + (f" (ROI {s['flat_win_roi']:+.1%})" if s["flat_win_roi"] is not None else ""))
    if s.get("brisnet_races"):
        L.append(f"Brisnet Power Play benchmark over {s['brisnet_races']} races: its top pick won {s['brisnet_pick_wins']}, "
                 f"winner in its Top 3: {s['brisnet_top3']}; 3-Star Best Bets {s['brisnet_best_bet_wins']}/{s['brisnet_best_bets']}")
        L.append("")
    if s.get("rd_races"):
        L.append(f"Racing Dudes benchmark over {s['rd_races']} races: their win pick won {s['rd_pick_wins']} (the engine's top pick {s['rd_engine_wins']} on the same races), "
                 f"winner in their four {s['rd_top4']}; Likely Winner {s['rd_likely_winner_wins']}/{s['rd_likely_winner']}")
        L.append("")
    if s.get("timeform_races"):
        L.append(f"TimeformUS benchmark over {s['timeform_races']} races: its top figure won {s['timeform_top_wins']}, winner in its top 3 by figure: "
                 f"{s['timeform_winner_in_top3']}; its first Power Pick won {s['timeform_power_pick_wins']}/{s['timeform_power_picks']}")
        L.append("")
    L.append("| Race | Winner | Winner rank | Eliminated? | Top pick | Hit | Win $2 | Brisnet pick | Timeform top |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in bt["races"]:
        bp = (f"#{r['brisnet_pick']}" + (" WIN" if r["brisnet_won"] else "") + (" (best bet)" if r["brisnet_best_bet"] else "")) if r.get("brisnet_pick") else ""
        tp = (f"#{r['timeform_top']}" + (" WIN" if r.get("timeform_won") else "") + (f" (winner rk {r['timeform_winner_rank']})" if r.get("timeform_winner_rank") else "")) if r.get("timeform_top") else ""
        L.append(f"| {r['race_no']} | #{r['winner']} | {r['winner_rank']} | {'yes' if r['winner_eliminated'] else ''} | #{r['top_pick']} | "
                 f"{'WIN' if r['top_pick_won'] else ('top3' if r['winner_in_top3'] else '')} | {r['win_payoff'] if r['win_payoff'] is not None else ''} | {bp} | {tp} |")
    L.append("")
    for key, m in bt["multirace"].items():
        if m.get("known"):
            L.append(f"- {m['name']}: winners {', '.join('#' + w for w in m['winners'])} -> {'HIT' if m['hit'] else 'miss'} (cost ${m['cost']:.2f})")
        else:
            L.append(f"- {m['name']}: results incomplete")
    L.append("")
    L.append("| Rule | Sign | Fired | Won | Win% | ITM% |")
    L.append("|---|---|---|---|---|---|")
    for st in bt["rules"]:
        L.append(f"| {st['rule']} | {st['sign']} | {st['fired']} | {st['won']} | {st['win_pct']} | {st['itm_pct']} |")
    if bt.get("angles"):
        L.append("")
        L.append("Power Play angles and ranks, Timeform marks, Racing Dudes roles, track-condition and race-type angles (prospective hit rates; no points are awarded for these):")
        L.append("")
        L.append("| Source | Label | Fired | Won | Win% | ITM% |")
        L.append("|---|---|---|---|---|---|")
        for st in bt["angles"]:
            L.append(f"| {st['kind']} | {st['label']} | {st['fired']} | {st['won']} | {st['win_pct']} | {st['itm_pct']} |")
    return "\n".join(L)
