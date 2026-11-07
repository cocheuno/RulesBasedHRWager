# Race Day Desk — UI design

Clickable mock-up of every screen, populated with the Del Mar 2026-11-06 card:
https://claude.ai/artifact/Vxj3sV3wcga5WocqG2XzXq

## Goals

Replace reading `pick.py` output in PowerShell with a local screen that lets one person, on race day:

1. load the day's documents (Ultimate PPs, the Power Play quick sheet, result screenshots) by dropping files;
2. press one button to run the engine, tick scratched horses, and re-run;
3. see, per race, the horses with program, post, morning line, rank, score, win chance and A/B grade, the
   primary play, the other wagers and the multi-race tickets, with the rule-by-rule audit one click away;
4. after the races, see the result, the payoffs and what each suggested wager would have returned;
5. look across days and tracks: hit rates and return by bet type, confidence, track and rule.

## Architecture: a local web app on the standard library

```
python ui.py                      # starts http://localhost:8765 and opens the browser
ui/                               # new package
  server.py                       # http.server + JSON API; shells nothing, imports the engine directly
  static/index.html, app.js, app.css   # one page, vanilla JS, no framework, no build step
handicapper/wagering.py           # NEW: evaluates suggested wagers against results (section "Wagering analysis")
data/cards/<card>.json            # NEW: per-card state the UI keeps (scratches, runs, which files are loaded)
```

Why a browser page served by Python rather than a Tkinter window: the output is tables, badges and
screenshots, which HTML renders well and Tkinter does not; the only dependency stays `pdfplumber`;
`python ui.py` works the same on Windows and in a cloud session.  The server binds to 127.0.0.1 only.

The API wraps what already exists, so the command line and the UI can never disagree:

| Call | Does | Existing code |
|---|---|---|
| `GET /api/cards` | list cards found under `data/pps`, with what is loaded for each | file system |
| `POST /api/cards/<card>/load` | copy a dropped file into `data/pps/` or `data/results-png/<card>/` | file system |
| `POST /api/cards/<card>/run` | parse (cached as `data/out/<card>.card.json`), apply scratches, sheet, results; score; write picks.json/.md | `parse_pdf`, `apply_scratches`, `merge_sheet`, `attach_day_bias`, `score_card` |
| `GET /api/cards/<card>/picks` | the latest run (`data/out/<card>.picks.json`) | file |
| `PUT /api/cards/<card>/scratches` | save the scratch list (also-eligibles draw in on the next run) | `parse_scratch_spec` |
| `POST /api/cards/<card>/results` | transcribe screenshots → `results/<card>.results.json` (see note), back-test, wagering analysis | `backtest`, `wagering.evaluate_card` |
| `GET /api/analysis?from=&to=&track=&bet=` | roll-up across cards | `wagering.rollup` |

Screenshot transcription: reading a PNG needs OCR, which is a new dependency.  Two options, in order:
(a) the UI shows the screenshot beside an entry form pre-filled from the picks (program numbers, names) and the
person types finish order and payoffs — the same fields `addresult.py` takes; (b) later, an optional OCR step
(`pytesseract`) behind a flag, never required.  The mock-up assumes (a).

## Screens

### Desk (`Main.dc.html` in the mock-up)

- **Top bar**: day and track selectors (cards found on disk), the card chip (code, profile, race count),
  status chips (PPs, quick sheet, scratches, results n/N), and the three actions: **Run picks**,
  which becomes **Re-run with scratches** when a scratch has changed since the last run, and **Process results**.
- **Race list** (left): one button per race with class, distance, confidence badge and, once known, the
  result chip (WIN / top 3 / miss).  Selecting a race fills the panel.
- **Race panel**, two tabs:
  - **Before the race**: horses table (scratch checkbox, program, post, name, ML, run style and points, rank,
    score, win chance, grade, top reasons; scratched rows dimmed; also-eligibles that drew in labelled), the
    primary play card, the other-wagers list, the multi-race tickets that include this race, and the
    rule-by-rule audit for the selected horse.
  - **After the race**: finish order, payoff table, the screenshot, and the **bet results** table (each
    suggested wager with cost, HIT/miss and return), plus "engine vs Brisnet" and the winner's audit summary.

### Load (`Load.dc.html`)

Three drop zones (PPs, quick sheet, result PNGs) with parse status, a scratch-list field with
**Apply and re-run picks**, the list of runs kept for the card, and an activity log.

### Analysis (`Analysis.dc.html`)

Filters (date range, track, bet type, confidence, profile); KPI tiles (bets, cost, return, ROI, hit rate,
top-pick win %, winner-in-top-3 %); tables by bet type, by confidence, by track and by rule (fired / won /
win % / ITM %, the back-test's per-rule table across cards); the engine-vs-Brisnet benchmark; a per-card list.

## Wagering analysis (`handicapper/wagering.py`)

The report already names every suggested wager in words.  The analysis needs them as structures:

```
wager = {"type": "WIN"|"EXACTA"|"TRIFECTA"|"SUPERFECTA"|"DOUBLE"|"PICK3"|"PICK4",
         "race_no": 4, "legs": [["7"], ["1","6","10"]],            # positions / legs, each a list of programs
         "box": false, "base": 1.0, "combos": 3, "cost": 3.0, "source": "other_wagers"|"primary"|"multirace"}
```

`engine.other_wagers` and `multirace` will return these alongside the text (the text stays for the report).
`wagering.evaluate_card(picks, results)` then, per wager: finds the matching pool in the results file (type +
base), checks whether the winning combo is covered (keys, boxes and part-wheels expand to combos; Pick N
across legs), scales the payout to the base bet, and records `{cost, hit, return}`.  `wagering.rollup(cards)`
aggregates by bet type, confidence, track, profile and rule.  Exotic pools missing from a results file are
reported as "unknown", never as a miss.

Policy decisions (in `rules_config.json -> wagering`): **$1 unit stake on every bet type**; **the "other wagers"
count as bets placed**; overlapping suggestions (the primary WIN and the "other" WIN on the same horse, a box inside
a part-wheel) are counted once; only the recommended Pick 3 / Pick 4 window counts, and only windows the track's
wager menu offers are built (rule H10).

### Hit / miss bar charts

The Analysis screen shows one horizontal stacked bar per track plus an **ALL** bar: successful bets (hits) and
unsuccessful bets (misses) side by side on one axis, with the counts at the bar ends and a legend; unknown
results (payout not on file) are excluded from the bar and listed beside it.  Filters above the chart (date
range, bet type, confidence) re-draw it.  Colors: hits blue `#2a78d6`, misses orange `#eb6834` (validated
colour-blind-safe pair); the by-track table under the chart is the accessible table view of the same data.

## Per-card state (`data/cards/<card>.json`)

```
{"card": "dmr1106y", "track_code": "DMR", "date": "2026-11-06",
 "files": {"pp": "data/pps/dmr1106y.pdf", "sheet": null, "pngs": ["r1.png", ...]},
 "scratches": "2:10, 4:2, 4:11, 4:12, 5:5, 6:7, 6:10, 7:13",
 "runs": [{"at": "2026-11-06T10:12:00", "scratches": "", "picks": "data/out/dmr1106y.picks.json"},
          {"at": "2026-11-06T11:48:00", "scratches": "...", "picks": "data/out/dmr1106y.picks.json", "bet_from": true}],
 "results": "results/dmr1106y.results.json"}
```

Kept under `data/` (ignored) except that `picks.json` and the results file are committed as today, so the
after-race processing can still run from any clone.

## Build order

1. `handicapper/wagering.py` + structured wagers from `other_wagers` / `multirace` (tests on the synthetic card
   and the Del Mar results) — useful on its own from the command line (`backtest.py` prints it).
2. `ui/server.py` with the run / picks / scratches API and the Desk screen (before tab).
3. Load screen and per-card state; results entry form and the after tab.
4. Analysis screen over `wagering.rollup`.

Each step is one PR; the command line keeps working throughout.
