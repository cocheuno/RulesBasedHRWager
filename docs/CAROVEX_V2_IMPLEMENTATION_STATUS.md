# Carovex Racing Engine V2 — implementation status

Updated at the end of every phase. Baseline audit: `main` d9216be, 2026-11-15, Python 3.13.18, 112 tests OK.

## Implemented and tested (baseline, before V2)

| Component | Where | Tests |
|---|---|---|
| Brisnet PP parser, surfaces incl. all-weather, 1m70y, debut runners | `brisnet_pp/parser.py` | `test_parser_rows.py`, synthetic card |
| Power Play sheet merge (key race F16, Brisnet benchmark) | `brisnet_pp/sheet.py` | `test_rules.py::TestKeyRaceSheet` |
| Chart reader incl. two-column mutuels, wrapped scratch lists | `brisnet_pp/chart.py` | `test_chart.py` |
| Equibase changes page reader | `brisnet_pp/changes.py` | `test_changes.py` |
| Rules (75+), track profiles, config validation | `handicapper/rules.py`, `engine.py` | `test_rules.py` |
| One probability model; value apart from ability | `handicapper/probability.py` | `TestAbilityAndValue`, `TestConfigValidation` |
| AE/MTO out of the active field; conditional scoring; draw-in tokens | `features.py`, `engine.py`, `results.py` | `TestAlternatesOutOfField`, `test_results.py` |
| Wagering: unit stakes, min win price, passed on price, not offered, tracked Pick 3/4, identity | `handicapper/wagering.py`, `results.py` | `test_wagering.py`, `TestIdentity` |
| Snapshots, run block, pre-race / post-results / as-run | `handicapper/snapshot.py`, `pipeline.py` | `test_ui.py` |
| Race Day Desk incl. stale-code banner, PP upload guard, result-edit provenance | `ui/` | `test_ui.py` |

## Phase status

| Phase | Status | Notes |
|---|---|---|
| 0 Audit | **done** (PR 51) | architecture, status, prompt and week review in `docs/` |
| A Timing and ledger | **done** (PR 52) | `handicapper/timing.py`, `snapshot.pre_race_by_race`, decision records in the run block, `carovex/ledger.py` (SQLite, migrations, import, `as_of`), price basis on every wager row |
| B Data and provenance | not started | TimeformUS reader prototype exists outside the repo; four sample PDFs in the owner's `data/pps` |
| C Tote (PuntersEdge) | not started | owner will supply `PUNTERSEDGE_API_KEY` when Phase C begins; schema to be read from the live OpenAPI document, never guessed |
| D Research probabilities, EV, place/show, wagering decisions | not started | depends on the decisions table |
| E Evaluation and data watch | not started | gates: 300 global, 400 per track, 150 tote, 200 Timeform |
| F Desk additions | not started | |

## Deliberately deferred (gated on prospective data, see Phase E)

Calibration fits of the softmax scale and market blend; track-specific refits; late-odds drift model;
hierarchical figure correction; conditional-logit race model; constrained Kelly; joint finishing-order exotic
pricing. Each stays `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA` until its gate is met.

## Blocked or awaiting the owner

- **Decisions table.** Confirmed by the owner on 2026-11-16; recorded in `docs/CAROVEX_V2_PROMPT.md`.
- **PuntersEdge key** for live checks in Phase C (replay fixtures do not need it).
- **Weather provider** (`python-weather`) availability and its data source's terms, to confirm in Phase B.

## Unverified vendor assumptions

- PuntersEdge: endpoint names, field names, odds convention, credit billing and retention rights are taken
  from the owner's prompt; all must be verified against the current OpenAPI document before any code names a key.
- TimeformUS: field meanings inferred from the PDF text layer (Top Fig, early/late pace figures, running style);
  Pace Projector order is a graphic and may not be recoverable from text.
- Equibase charts: the `surface` field is unreliable (reads "DIRT" everywhere); fix in Phase B.

## Phase A note: the week re-scored by the clock

With per-race cutoffs from the charts' actual off times, 19 of the 23 frozen-week cards have a before-cutoff run
for most races (176 races; 2 excluded); the four 11/07 cards have none, because their only runs were made the
following evening. On those 176 races the top pick won 56 (32%) and the counted bets lost 41% ($3,356.60 →
$1,967.51), against −32% when the evening runs with the final scratches were scored. The clock is stricter, and
that is the number to carry forward.

## Data on file (2026-11-15)

25 cards with picks, 157 snapshots, 25 results files; 219 races with pre-race snapshots and chart results;
79 races with a Timeform comparison; 0 tote observations.
