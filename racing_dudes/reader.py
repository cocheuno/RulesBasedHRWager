"""Read the Racing Dudes premium picks dashboard, saved from the browser as HTML ("Webpage, HTML only").

One page holds every track on the subscriber's list and, per track, a tab per race date (usually today and
tomorrow).  The markup this reader keys on (checked against the 2026-11-20 page):

  <a class="option single-track-filter" data-tid="72515">Belmont Park</a>         track id -> name
  <section class="track" id="track-picks-72515" data-tid="72515">                   one track
  <div class="tab-panel" id="2026-11-20-picks-72515">                               one race date
  <div class="r"> <div class="r-excerpt"> <div class="race-tags"><span class="sr-only">Likely Winner</span>
      <h4 class="race-name"> 1 Maiden Special Weight</h4> <div>9:40 am PST</div> <div>1 Mile</div> <div>Dirt</div>
    <div class="r-content"> <div class="c-heading">Win</div> ... <span class="lane-number num-7">7</span> Mr. Miracle
      <p>9-5<br> J: F Prat<br />T: C C Brown</p>   (then Place, Show, Next Best)
      <table class="wagers"> <strong>Exacta</strong><br />2,3,7 BOX ... Trifecta ... Multi Race

parse_page(html) -> {"source": "racing_dudes", "tracks": [{"tid", "name", "days": {"2026-11-20": {race_no: race}}}]}
race = {"race_no", "class_text", "post_time", "distance_text", "surface", "tags": [...], "likely_winner", "best_value",
        "picks": [{"role": "Win"|"Place"|"Show"|"Next Best", "pgm", "name", "ml", "jockey", "trainer"}],
        "order": [pgm, ...], "wagers": {"exacta": "2,3,7 BOX", "trifecta": ..., "multi_race": ...}}

Their picks are an opinion built from the same past performances the engine reads.  They are merged under
race["racing_dudes"] / horse["racing_dudes"], shown beside the engine's rank and scored in the back-test.  Nothing
here is a Brisnet or Timeform value, and no rule reads it.
"""
from __future__ import annotations

import html as _html
import os
import re

READER_VERSION = "rd-1"
ROLES = ("Win", "Place", "Show", "Next Best")


def _text(fragment: str) -> list[str]:
    t = re.sub(r"(?i)<br\s*/?>", "\n", fragment or "")
    t = _html.unescape(re.sub(r"<[^>]+>", "", t))
    return [re.sub(r"\s+", " ", x).strip() for x in t.split("\n") if re.sub(r"\s+", " ", x).strip()]


def is_racing_dudes(text: str | bytes) -> bool:
    head = text[:400000] if isinstance(text, str) else text[:400000].decode("utf-8", errors="replace")
    return "racingdudes" in head.lower() and ("track-picks-" in head or "race-name" in head)


def _track_names(page: str) -> dict[str, str]:
    names = {}
    for tid, name in re.findall(r'data-tid="(\d+)"[^>]*>\s*([^<]+?)\s*</a>', page):
        names.setdefault(tid, _html.unescape(name).strip())
    for tid, name in re.findall(r'data-tid="(\d+)"[^>]*data-track-name="([^"]+)"', page):
        names.setdefault(tid, _html.unescape(name).strip())
    return names


def _races(panel: str) -> dict[int, dict]:
    out = {}
    starts = [m.start() for m in re.finditer(r'<div class="r-excerpt"', panel)]
    for i, s in enumerate(starts):
        chunk = panel[s: starts[i + 1] if i + 1 < len(starts) else len(panel)]
        m = re.search(r'<h4 class="race-name">\s*(\d{1,2})\s+([^<]*)</h4>', chunk)
        if not m:
            continue
        rn = int(m.group(1))
        tags = [_html.unescape(x).strip() for x in re.findall(r'<span class="sr-only">\s*([^<]+?)\s*</span>', chunk.split('<h4', 1)[0])]
        cells = [(_text(c) or [""])[0] for c in re.findall(r'<div class="c c-2">(.*?)</div>', chunk.split('<div class="r-content"', 1)[0], re.S)]
        race = {"race_no": rn, "class_text": _html.unescape(m.group(2)).strip() or None,
                "post_time": cells[0] if len(cells) > 0 else None, "distance_text": cells[1] if len(cells) > 1 else None,
                "surface": cells[2] if len(cells) > 2 else None, "tags": tags,
                "likely_winner": any(t.lower() == "likely winner" for t in tags), "best_value": any(t.lower() == "best value" for t in tags),
                "best_bet": any("best bet" in t.lower() for t in tags), "picks": [], "order": [], "wagers": {}}
        content = chunk.split('<div class="r-content"', 1)[1] if '<div class="r-content"' in chunk else ""
        for pm in re.finditer(r'<div class="c-heading">\s*(Win|Place|Show|Next Best)\s*</div>(.*?)(?=<div class="c-heading">|<table class="wagers"|$)', content, re.S):
            body = pm.group(2)
            num = re.search(r'<span class="lane-number[^"]*">\s*([0-9]{1,2}[A-Za-z]?)\s*</span>\s*([^<]*)', body)
            if not num:
                continue
            lines = _text((re.search(r"<p>(.*?)</p>", body, re.S) or [None, ""])[1])
            ml = next((x for x in lines if re.fullmatch(r"\d+(?:\.\d+)?-\d+|\d+/\d+", x)), None)
            jockey = next((x[2:].strip() for x in lines if x.startswith("J:")), None)
            trainer = next((x[2:].strip() for x in lines if x.startswith("T:")), None)
            pick = {"role": pm.group(1), "pgm": num.group(1).upper(), "name": _html.unescape(num.group(2)).strip(), "ml": ml,
                    "jockey": jockey, "trainer": trainer}
            race["picks"].append(pick)
            if pick["pgm"] not in race["order"]:
                race["order"].append(pick["pgm"])
        for wm in re.finditer(r"<strong>\s*([^<]+?)\s*</strong>\s*<br\s*/?>\s*([^<]*)", content):
            race["wagers"][re.sub(r"\W+", "_", wm.group(1).strip().lower())] = _html.unescape(wm.group(2)).strip()
        out[rn] = race
    return out


def parse_page(page: str | bytes, source: str | None = None) -> dict:
    if isinstance(page, bytes):
        page = page.decode("utf-8", errors="replace")
    page = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", page)
    names = _track_names(page)
    out = {"source": "racing_dudes", "reader_version": READER_VERSION, "file": os.path.basename(source) if source else None, "tracks": []}
    secs = list(re.finditer(r'<section class="track[^"]*"[^>]*data-tid="(\d+)"', page))
    if not secs:                                  # a single-track page (an archive page, say): one section, the whole page
        tid = (re.search(r'data-tid="(\d+)"', page) or [None, None])[1] or "0"
        secs_spans = [(tid, 0, len(page))]
    else:
        secs_spans = [(m.group(1), m.start(), secs[i + 1].start() if i + 1 < len(secs) else len(page)) for i, m in enumerate(secs)]
    for tid, a, b in secs_spans:
        sec = page[a:b]
        days = {}
        panels = list(re.finditer(r'<div class="tab-panel[^"]*" id="(\d{4}-\d{2}-\d{2})-picks-\d+"', sec))
        for i, p in enumerate(panels):
            body = sec[p.end(): panels[i + 1].start() if i + 1 < len(panels) else len(sec)]
            races = _races(body)
            if races:
                days[p.group(1)] = races
        if not panels:
            d = re.search(r"(\d{4}-\d{2}-\d{2})", sec)
            races = _races(sec)
            if races and d:
                days[d.group(1)] = races
        if days:
            out["tracks"].append({"tid": tid, "name": names.get(tid), "days": days})
    return out


def track_day(doc: dict, date: str | None, track_code: str | None = None, track_name: str | None = None, cfg: dict | None = None) -> dict | None:
    """The races for one track and date: {race_no: race}, matched by name through rules_config.json's aliases."""
    from handicapper.identity import canonical_track, norm_name
    code = (track_code or "").upper()
    want = norm_name(track_name)
    for t in doc.get("tracks", []):
        tc = canonical_track(t.get("name"), cfg)
        if (code and tc and tc == code) or (want and norm_name(t.get("name")) == want):
            return (t.get("days") or {}).get(str(date)) if date else None
    return None


def merge_racing_dudes(card: dict, races: dict | None, source: str | None = None) -> list[str]:
    """Attach the picks to a parsed card: race["racing_dudes"] and, for their four horses, horse["racing_dudes"]
    with the role and rank.  Matching by race number then program number, confirmed by the first word of the name."""
    from handicapper.identity import norm_name
    notes = []
    if not races:
        return ["no Racing Dudes picks for this track and date"]
    for race in card["races"]:
        r = races.get(race["race_no"]) or races.get(str(race["race_no"]))
        if not r:
            race["racing_dudes"] = None
            notes.append(f"R{race['race_no']}: not in the Racing Dudes page")
            continue
        by_pgm = {h["pgm"].upper(): h for h in race["horses"]}
        order, roles = [], {}
        for i, p in enumerate(r["picks"], 1):
            h = by_pgm.get(p["pgm"])
            if h is None or (p["name"] and h.get("name") and norm_name(p["name"]).split()[:1] != norm_name(h["name"]).split()[:1]):
                notes.append(f"R{race['race_no']} #{p['pgm']}: Racing Dudes says {p['name']!r}, card says {(h or {}).get('name')!r}; not matched")
                continue
            h["racing_dudes"] = {"role": p["role"], "rank": i, "ml": p["ml"], "source": "racing_dudes"}
            order.append(h["pgm"]); roles[h["pgm"]] = p["role"]
        race["racing_dudes"] = {"order": order, "roles": roles, "tags": r["tags"], "likely_winner": r["likely_winner"],
                                "best_value": r["best_value"], "best_bet": r["best_bet"], "wagers": r["wagers"],
                                "reader_version": READER_VERSION, "file": source}
    return notes


def benchmark(root: str, doc: dict, cfg: dict | None = None) -> dict:
    """Score a page (today's, or an archive page for a past date) against the results on file: their win pick, their
    top four, Likely Winner, against the engine's pre-race top pick on the same races.  Read-only."""
    import json
    from handicapper.engine import load_config
    from handicapper.identity import canonical_track
    from handicapper.results import load_results
    from handicapper.snapshot import pre_race_by_race
    cfg = cfg or load_config(os.path.join(root, "rules_config.json"))
    rows = []
    for t in doc.get("tracks", []):
        code = canonical_track(t.get("name"), cfg)
        if not code:
            continue
        for date, races in t["days"].items():
            for rp in sorted(os.listdir(os.path.join(root, "results"))) if os.path.isdir(os.path.join(root, "results")) else []:
                if not rp.endswith(".results.json"):
                    continue
                card = rp.split(".")[0]
                pj = os.path.join(root, "data", "out", f"{card}.picks.json")
                if not os.path.exists(pj):
                    continue
                with open(pj, encoding="utf-8") as fh:
                    meta = json.load(fh)
                if (meta.get("track_code") or "").upper() != code or str(meta.get("date")) != date:
                    continue
                res = load_results(os.path.join(root, "results", rp))
                snap = pre_race_by_race(os.path.join(root, "data", "out"), card, res, (cfg.get("tracks", {}).get(code) or {}).get("timezone"), 2)
                eng = {r["race_no"]: r for r in (snap or {}).get("races", [])}
                for x in res.get("races", []):
                    r = races.get(x["race_no"])
                    if not r or not x.get("finish") or not r["order"]:
                        continue
                    from handicapper.results import winners_of
                    wins = winners_of(x)
                    w = wins[0]
                    live = [s for s in (eng.get(x["race_no"]) or {}).get("sheets", []) if not s["eliminated"] and not s["flags"]]
                    rows.append({"card": card, "track": code, "date": date, "race_no": x["race_no"], "winner": w,
                                 "rd_pick": r["order"][0], "rd_won": r["order"][0] in wins, "rd_top4": any(v in r["order"] for v in wins),
                                 "likely_winner": r["likely_winner"], "best_value": r["best_value"],
                                 "win_payoff": x.get("win"), "engine_pick": live[0]["pgm"] if live else None,
                                 "engine_won": bool(live) and live[0]["pgm"] in wins, "agree": bool(live) and live[0]["pgm"] == r["order"][0]})
    n = len(rows)

    def roi(sel):
        bet = 2.0 * len(sel)
        ret = sum((r["win_payoff"] or 0) for r in sel if r["rd_won"])
        return round((ret - bet) / bet, 3) if bet else None
    lw = [r for r in rows if r["likely_winner"]]
    agree = [r for r in rows if r["agree"]]
    dis = [r for r in rows if r["engine_pick"] and not r["agree"]]
    return {"races": n, "rd_pick_wins": sum(r["rd_won"] for r in rows), "rd_top4": sum(r["rd_top4"] for r in rows),
            "engine_wins": sum(r["engine_won"] for r in rows), "rd_flat_win_roi": roi(rows),
            "likely_winner": {"races": len(lw), "wins": sum(r["rd_won"] for r in lw), "roi": roi(lw)},
            "agree": {"races": len(agree), "wins": sum(r["rd_won"] for r in agree)},
            "disagree": {"races": len(dis), "rd_wins": sum(r["rd_won"] for r in dis), "engine_wins": sum(r["engine_won"] for r in dis)},
            "rows": rows}


def format_benchmark(b: dict) -> str:
    if not b["races"]:
        return "No races on the page match a card with results on file."
    L = [f"Racing Dudes against the results on file: {b['races']} races",
         f"  their win pick won {b['rd_pick_wins']} ({b['rd_pick_wins'] / b['races']:.0%}); winner in their four {b['rd_top4']} ({b['rd_top4'] / b['races']:.0%}); "
         f"flat $2 on their win pick {b['rd_flat_win_roi']:+.1%}" if b["rd_flat_win_roi"] is not None else "",
         f"  engine's top pick on the same races won {b['engine_wins']} ({b['engine_wins'] / b['races']:.0%})",
         f"  Likely Winner: {b['likely_winner']['wins']} of {b['likely_winner']['races']}" + (f", flat $2 {b['likely_winner']['roi']:+.1%}" if b["likely_winner"]["roi"] is not None else ""),
         f"  agree on the top pick: {b['agree']['races']} races, won {b['agree']['wins']}; disagree: {b['disagree']['races']} races, "
         f"theirs won {b['disagree']['rd_wins']}, the engine's won {b['disagree']['engine_wins']}"]
    return "\n".join(x for x in L if x)


def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(prog="python -m racing_dudes.reader", description="Racing Dudes saved page: read, or score against the results on file")
    ap.add_argument("cmd", choices=["read", "benchmark"])
    ap.add_argument("pages", nargs="+")
    ap.add_argument("--root", default=os.getcwd())
    a = ap.parse_args(argv)
    docs = []
    for p in a.pages:
        with open(p, "rb") as fh:
            docs.append(parse_page(fh.read(), p))
    if a.cmd == "read":
        for d in docs:
            for t in d["tracks"]:
                print(f"{t['name']} ({t['tid']}): " + ", ".join(f"{day} {len(r)} races" for day, r in t["days"].items()))
        return 0
    merged = {"tracks": [t for d in docs for t in d["tracks"]]}
    b = benchmark(a.root, merged)
    print(format_benchmark(b))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
