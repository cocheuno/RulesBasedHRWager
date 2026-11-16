# Carovex Racing Engine V2 — architecture (baseline and transition plan)

Phase 0 audit of `main` at **d9216be** (2026-11-15), Python 3.13.18, `python -m unittest discover -s tests`:
**112 tests, OK**, no pre-existing failures. Keep this document current at the end of every phase.

## 1. What exists (the actual baseline)

Pure Python, one third-party runtime dependency (`pdfplumber`); OCR (`rapidocr_onnxruntime`) optional. About
7,300 lines across the modules below, 10 test modules, synthetic fixtures only.

| Area | Module | Lines | Role |
|---|---|---|---|
| Inputs | `brisnet_pp/parser.py` | 1060 | Brisnet Ultimate PP PDF → card dict (coordinate based; `PARSER_VERSION` stamped) |
| | `brisnet_pp/sheet.py` | 131 | Power Play quick sheet → key-race angles, Brisnet picks (benchmark) |
| | `brisnet_pp/chart.py` | 274 | Equibase result chart PDF → finish, payouts, final odds, runners, condition |
| | `brisnet_pp/changes.py` | 126 | Equibase race-day-changes page (saved HTML) → scratches, conditions, rail, jockey changes, pools not offered |
| | `handicapper/ocr.py`, `ocr_results.py` | 387 | payout-page screenshots → results (fallback to charts) |
| Engine | `handicapper/features.py` | 475 | per-horse features; race context over the active field (AE/MTO out) |
| | `handicapper/rules.py` | 1295 | 75+ pure rules `@rule(id, name, category, weight)`, docstring with Basis; X rules eliminate/flag |
| | `handicapper/engine.py` | 579 | config layering and validation, `score_race`, selection, win price, wagers, reports |
| | `handicapper/probability.py` | 94 | one win-probability model: softmax of the ability score (scale 18) blended with the renormalised morning line (0.35); fair odds from the model side; `elim_floor` for ticket pricing |
| | `handicapper/multirace.py` | 480 | Pick 3 / Pick 4 construction, H1–H10, hit probability × `hit_prob_shrink` |
| | `handicapper/wagering.py` | 365 | wager structures, unit stakes, evaluation, passed-on-price, not-offered, tracked tickets, roll-up |
| | `handicapper/results.py` | 266 | results file, scratches and draw-ins, same-day bias, identity check, back-test |
| | `handicapper/pipeline.py` | 118 | `run_card()`: parse or load, sheet, scratches, changes, results → score; run block |
| | `handicapper/snapshot.py` | 80 | append-only snapshots `data/out/snapshots/<card>/<UTC>_<kind>.picks.json` |
| Phase B | `timeform_pp/reader.py` | | TimeformUS PP text layer → figures, pace figures, style, lines with dates, Power Picks, Pace Projector; merged under `timeform` |
| | `handicapper/provenance.py` | | parser field audit; raw / derived values with source and date; as-of filtering; missingness flags |
| | `handicapper/weather.py` | | fetched (python-weather) and manual weather observations; newest before a race's cutoff |
| | `handicapper/identity.py` | | canonical track / race / betting-interest mapping across sources; coupled entries; review list |
| Phase C | `carovex/tote.py` | | PuntersEdge `/v1/racing/tote` client (keep-alive, gzip, retries, `Retry-After`), replay provider, board normalisation and public allocation, immutable capture, polling plan and credit cap, decision marks (`paper` / `accepted (verified)`), CLI |
| Front ends | `pick.py`, `backtest.py`, `validate_parse.py`, `addresult.py` | | CLI |
| | `ui/server.py`, `ui/static/{index.html,app.js,app.css}`, `ui.py` | 677 + 273 | Race Day Desk: Load / Desk / Analysis; start/stop; stale-code banner; upload guards |
| Config | `rules_config.json` | | `weights`, `disabled`, `selection`, `probability`, `multirace`, `wagering`, `tracks` (profiles), `track_aliases`; validated at load |

### Data flow for one card

```
Brisnet PP PDF ──parser──► card dict ──┐
Power Play sheet ──sheet.merge────────┤
Equibase changes page ──changes───────┤  scratches (typed, page, r:+p/r:-p tokens) ──► apply_scratches (AE draw-in)
results on file ──attach_day_bias─────┘
                     │
                     ▼ score_card(card, cfg)
   per race: horse_features ─► race_context (active field) ─► rules ─► ability score ─► eliminations/flags
             probability.race_probs (live horses) ─► model_prob / market_prob / win_prob / fair_odds / value(V1)
             select (gaps, confidence) ─► primary_wagers + other_wagers (min win price, field-size gates)
   card:     multirace.build_all (legs from leg_summary, H1–H10, tracked tickets)
                     │
                     ▼ picks.json (latest) + picks.md + snapshot (append-only, run block)
charts / screenshots ──chart.py / ocr.py──► results/<card>.results.json (identity-checked against the card)
                     │
                     ▼ backtest (per race, per rule, multirace) + evaluate_card (per wager: placed / passed / not offered /
                       tracked; unit stakes; returns from chart payouts) ──► results/<card>.backtest.md, Analysis screen
```

### Where things originate today

| Quantity | Origin | Status |
|---|---|---|
| Ability score, rank, eliminations | `engine.score_race` from `rules.py` | explainable, expert weights, track profiles |
| Win probability | `probability.race_probs`: softmax(score/18) × 0.65 + morning line × 0.35 | heuristic constants, labelled |
| Fair odds, value (V1) | model side of the probability vs morning line | heuristic; never in the score |
| Minimum win price | `engine.win_price`: max(3/2, fair × 1.15) | to be replaced by the EV formula (Phase D) |
| Wager suggestions | `engine.primary_wagers`, `other_wagers`, `multirace` | per confidence; owner's policy (see prompt) |
| "Placed" vs "passed" | `wagering.evaluate_wager` against the chart's final odds | assumed-price proxy (Phase A labels it) |
| Pre-race, per race | `timing.race_cutoffs` in the run block; `snapshot.pre_race_by_race` picks, for each race, the newest run made ≥ `timing.cutoff_margin_minutes` before the chart's off time (track timezone from `tracks.<code>.timezone`) or the PP's scheduled post (Eastern value of the four-zone string) | Phase A; legacy runs without clock evidence are `unverified` |
| Decision records | `pipeline.run_card`: `wager.decision{id, at_utc, cutoff_status, price_basis, status, hashes}` | per run, never edited; `status` moves only through the ledger's execution rows (Phase C) |
| Price basis | `wagering.evaluate_wager`: `assumed-final` / `unpriced` / `observed` | an `accepted` decision is never passed by final odds |
| Ledger | `carovex/ledger.py`: SQLite `data/private/carovex.db`, schema v1, `import_card`, `as_of` time-travel | legacy results carry `received_at` = import time |
| Results identity | `results.check_identity` (track, date, chart's own track) | enforced |
| Same-day bias (P10) | `results.attach_day_bias`, earlier races' results only | no leakage by construction |

### Artifacts and their schemas

- `data/out/<card>.picks.json` (latest run; rewritten): `source, track, track_code, date, track_profile, races[],
  multirace, scratches, parser_version, run_notes, run{at_utc, scratches, parser_version, config_hash,
  track_profile, code_version, source, source_sha256, sheet, results_known, odds_source, changes, kind}`.
  Each race: `race_no, class_text, distance_text, surface, field_size, alternates, pars, pace_shape, lone_speed,
  num_early, picks, bet_structure, confidence, selection_note, brisnet, wagers_menu, sheets[], leg, wagers[],
  other_wagers[]`. Each sheet: `pgm, name, ml_odds, ml_decimal, run_style, speed_pts, prime_power, score,
  eliminated, flags, hits[{rule, name, points, note, value?}], features{}, model_prob, market_prob, win_prob,
  implied_prob (alias), fair_odds, value{label, points, edge}, rank, conditional_rank, min_win_odds`. Each wager:
  `type, legs, box, combos, label, source, race_no, races, min_odds, min_odds_by, unit?`.
- `data/out/snapshots/<card>/<UTC>_<kind>.picks.json`: the same, minus `features`, plus `snapshot{kind, at_utc,
  file}`. Kinds: `pre-race`, `post-results`, `as-run`. Append-only; 157 on file for 25 cards.
- `results/<card>.results.json`: `track, date, _source, races[{race_no, finish[], win, place{}, show{},
  exotics[{type, base, combo, payout}], track_condition, surface, official, distance_text, class_text, purse,
  times, off_at, final_odds{}, runners[], scratched[], claimed[], source, track, ocr{}, corrections[]?}]`.
- `data/cards/<card>.json` (ignored): Desk state (scratches, runs, activity, changes summary).

### Known gaps in the baseline (from the frozen-week review)

- Pre-race is a card-level label decided by the absence of results, not a per-race clock. Runs made after a
  race with results not yet loaded are labelled pre-race.
- The chart reader's `surface` field reads "DIRT" for every race; off-turf switches are not applied to the card.
- No track-condition or weather input reaches a rule. No tote or live odds input exists.
- Eliminated horses have probability 0 outside ticket pricing. Coupled entries (1, 1A) are separate program
  numbers in wager combinations.
- The 25 existing cards are not an unbiased sample: engine versions changed through 11/06, scratches were
  entered after some races on 11/12 and 11/13, and 11/06 has no snapshots.

## 2. Target shape (V2)

Additive layers around the existing engine, each behind its own PR:

```
inputs (Brisnet, Power Play, Timeform, Equibase changes, weather, PuntersEdge tote)
   └─ source_observation (provenance, available_at, hashes)            ← Phase B, C
engine (unchanged rule core) ─► forecast (p_rule_heuristic | q_live_market | p_market_anchor | p_final_model) ← Phase D
decision service (EV, O_min, NO_BET codes, status suggested/paper/accepted) ─► decision records             ← Phase A, D
ledger: SQLite data/private/carovex.db (race, betting_interest, source_observation, forecast, decision,
        execution, settlement) with time-travel query                                                      ← Phase A
settlement from charts ─► evaluation (per-race cutoff, assumed vs observed price, data watch)               ← Phase A, E
Race Day Desk: existing screens + Market view + weather box + plain-English horse text                      ← Phase F
```

Legacy JSON stays the source of truth for picks and results; the ledger indexes it and holds what JSON cannot.

## 3. Phased transition plan

| Phase | Deliverable | Behaviour change |
|---|---|---|
| 0 | this document, status document, prompt and week review in `docs/` | none |
| A | per-race cutoffs from PP post times + track timezones; assumed-price labels; decision records in the run block; SQLite ledger with import and time-travel query; tests (i)–(vi) | scoring of the back-test only |
| B | field audit of the Brisnet parser; Power Play angles as typed features; `timeform_pp/` reader and Desk drop zone; Equibase condition / off-turf / pools-not-offered as inputs; weather (python-weather + manual); canonical identity with coupled entries | inputs only; rules read new inputs only where the decisions table says |
| C | PuntersEdge tote adapter, replay provider, polling policy with credit cap, capture, public allocation, last-minute mode, CLI and API | none to picks |
| D | research probabilities, EV and `O_min`, NO_BET codes, place and show candidates, the owner's wagering decisions from the table | wagering policy as decided |
| E | evaluation metrics, data watch with gates, deferred-model interfaces | none |
| F | Market view, weather entry, scratch-toggle fix, Simplified Technical English on every horse-facing string | presentation |
