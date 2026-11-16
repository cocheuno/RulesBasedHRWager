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
| B Data and provenance | **done** (this PR) | `handicapper/provenance.py` (field audit, as-of records, missingness), typed Power Play angles with back-test hit rates, `timeform_pp/reader.py` + Desk drop zone + side-by-side ranks, Equibase condition / off-turf / pools as inputs (off-turf switch applied), `handicapper/weather.py` (python-weather + manual), `handicapper/identity.py`, chart surface fix |
| C Tote (PuntersEdge) | **done** (this PR) | `carovex/tote.py`: `ToteProvider` / `PuntersEdgeProvider` / `ReplayToteProvider`, normalised boards with public allocation and explicit odds convention, immutable capture with heartbeats, polling plan with a daily credit cap, Desk refresh / Tote column / last-minute check with `paper` and `accepted (verified)` marks, CLI `sample` / `poll` / `result` / `replay` / `usage` |
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
- **Weather provider**: `python-weather` 2.2.7 installs and wraps wttr.in; whether wttr.in is reachable from the owner's
  machine is confirmed only by the first Desk run with a configured track location (the run block says `ok` or
  `unavailable` with the reason). Terms: wttr.in is a free public service without an SLA; nothing here depends on it.

## Unverified vendor assumptions

- PuntersEdge: **verified on 2026-11-16** against `https://api.puntersedge.online/openapi.json` (schema `ToteRaceOut`)
  and live calls. The US tote is `GET /v1/racing/tote` (TVG's public board): one call returns every US and Canadian
  race of a US Eastern date for 2 credits; `history=true` / `exotics=true` for one race (`source_race_id`
  ``tvg_<track>_<date>_<n>``). `win_odds` is a fraction string of odds to 1 (net, as displayed), `win_decimal`
  the gross multiple; null before the WIN pool opens and on a scratched runner. Credits and the per-minute limit
  come back as `X-Credits-*` and `X-Ratelimit-*` headers (30 requests a minute on the free plan). The key goes in
  the `X-API-Key` header with no prefix; a Bearer token is refused. The free plan holds 1,500 credits a month; the
  provider keeps a race's tote history from 2026-10-26. `/v1/racing/results` returned nothing for a TVG race id,
  so settlement stays with the Equibase charts. TVG's codes for BEL, CD, DMR and GP equal Brisnet's (Parx is PHI,
  a `tvg_code` field on a track profile covers such cases).
- TimeformUS: field meanings inferred from the PDF text layer (Top Fig, early/late pace figures, running style);
  Pace Projector order is a graphic and may not be recoverable from text.
- Equibase charts: the `surface` field read "DIRT" everywhere (236 of 236 races on file, 29 of them FIRM). Phase B reads
  the surface from the header parenthetical ("(Turf)", "(Tapeta)") and, failing that, from the OFF AT line case-
  insensitively with turf-only conditions (firm / yielding / soft) counted as turf; `surface_source` says which.
  Results already on file keep their old value until the charts are re-read (Load tab, Process results).

## Phase A note: the clock is a label

The owner's rule: picks and results are often run late in the day or the next day, and that does not compromise
the data, because a run uses only the PPs and the public scratches. Scoring therefore takes, per race, the newest
run made without that race's result, whatever the hour, and records whether it was before or after the cutoff.
The frozen week scores as before (23 cards, 219 races, top pick 30%, counted bets −32%); of those 219 race
predictions, 4 were made before the cutoff and 215 after, which the clock column now shows.

## Phase B note: what the forms say that the rules do not read

`python -m handicapper.provenance audit <card.json>` lists, per object, the parser fields the rules code never
names. On the synthetic card (the real cards carry the same keys):

- race: `age_text`, `conditions`, `fillies_mares`, `header_text`, `pages`, `purse`, `racetype_stats`, `rankings`, `sex_text`, `state_bred`, `top3`
- horse: `apprentice_allowance`, `bred_state`, `breeder`, `claim_price`, `color`, `foal_month`, `lasix`, `lifetime_starts`, `name_flag`, `owner`, `sale`, `silks`, `sire_sire`, `stud_fee`, `trainer`
- running line: `about_or_alt_course`, `age_restriction`, `apprentice`, `blinkers`, `c1`, `c2`, `coupled_entry`, `fillies_mares`, `final_time`, `finish`, `foreign`, `fractions`, `front_wraps`, `lasix`, `med_equip_raw`, `race_type_raw`, `raw`, `start`, `state_bred`, `top_finishers`, `top_finishers_raw`, `track_condition`
- work: `condition`, `time`

All of them are now exposed with source and date through `provenance.horse_record` / `card_records`, with
missingness flags, and a feature vector "as of T" (`features_as_of`) contains no line or work dated after T. No
rule reads any new field; that waits for Phase E's comparison and the owner's approval.

Power Play angles are kept as typed features with their printed label (`horse["sheet"]`: angles, speed / class /
pace / top-three ranks, top pick, best bet); the back-test's new "angles" table reports each label's prospective
win and in-the-money rate. On the sheet on file (Gulfstream 11/07) the labels are HotTrainer, BlueChipTrainerPlay,
DistanceSpecialist, HotJockey, HorseForCourse, ExitPossibleKeyRace, HotTnr/JkyCombo, ExitKeyRace.

TimeformUS: `timeform_pp/reader.py` reads the text layer (Top Fig including the three-digit garble, running style
with early and late pace figures, ML, weight, every running line with its own date, Power Picks, Pace Projector
order when the digits come through, marked `text-layer` or `text-layer (partial)`). On the seven real files
(11/14 and 11/15, four tracks) every non-debut horse has a Top Fig; on 11/15: BEL 63 horses, CD 100, DMR 66,
GP 94. The Desk's Load tab takes the PDF beside the Brisnet one with the same identity guard; the Desk table and
the report show `TF rk/fig` beside the Brisnet rank. No rule reads it.

Equibase changes: each race now carries `inputs` (morning condition for its surface, `off_turf`, pools not
offered, rail, notes). A race the page takes off the turf is scored on `tracks.<code>.off_turf_surface` (dirt, or
`aw` at Gulfstream) with its MTO entrants activated and `surface_switch` recorded; this is the one input change
that can move a pick, as the decisions table asks. Pools not offered are recorded only; suppression is Phase D.

Weather: `handicapper/weather.py` fetches one forecast observation per race post time when the track has a
`location` (Desk runs do this; `pick.py --weather`), or records `unavailable` with the reason. The owner's typed
weather is a `manual` observation (`POST /api/cards/<card>/weather`, text box in Phase F); the newest observation
at or before a race's cutoff is the one a rule may read. Nothing reads it yet.

Identity: `handicapper/identity.py` maps every source onto the card's betting interests (1 and 1A one interest),
confirms by name, records program changes, and sends anything ambiguous to a review list.

Verification: on the two real cards available to the session (gpx1107y with its Power Play sheet, bel1106y),
scores, ranks, win probabilities, picks, wagers and Pick 3 / Pick 4 tickets are identical to `main`.

## Phase C note: credits and what one read buys

One board read is 2 credits whatever the number of races, so a read serves every track at once. The polling
plan reads nothing until 60 minutes before a race of interest, every 5 minutes until 15, every minute until 5,
every 30 seconds inside 5 and stops at off / official; a race day of four tracks that follows it closely costs
roughly 200 to 400 credits, more than the free plan's 1,500 a month supports every day. `tote.daily_credit_cap`
(60 by default, about 30 reads) bounds the spend and the Desk's Refresh button is manual, so the free plan serves
an owner who refreshes the races they are present for. The complete odds path of a finished race costs 2 credits
with `history=true` (`python -m carovex.tote result <card> <race>`), which is the cheap way to capture a whole
race's market after the fact. The hobby plan (7,500 credits, AUD 9 a month) would cover a daily history fetch for
four tracks; the owner decides.

## Data on file (2026-11-15)

25 cards with picks, 157 snapshots, 25 results files; 219 races with pre-race snapshots and chart results;
79 races with a Timeform comparison; 0 tote observations.
