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
| D Research probabilities, EV, place/show, wagering decisions | **done** (this PR) | `handicapper/research.py` (p_rule_heuristic / q_live_market / p_market_anchor, model status, EV, O_min, break-even, scenarios, NO_BET codes, Harville place/show), `handicapper/policy.py` (the decisions table applied to suggested wagers, every suppression recorded), PLACE / SHOW settlement and roll-up, O_min replaces fair x 1.15 |
| E Evaluation and data watch | **done** (this PR) | `handicapper/evaluation.py` (log loss with floor, Brier, reliability, by field / track / surface / condition / pace / clock, gap to final odds, bootstrap and Wilson intervals, candidate blends on a chronological split, data watch), `handicapper/deferred.py` (model interfaces that refuse to fit until their gate is met), Analysis panel, `docs/DATA_WATCH.md`, `docs/EVALUATION.md` |
| F Desk additions | **done** (this PR) | Market view, weather text box beside the forecast, scratch-toggle comparison with the last run, best bets of the day as a labelled view, plain English on every horse-facing string with `docs/GLOSSARY.md` and a test, `.env.example` and the Windows / PowerShell set-up |

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
- TimeformUS: field meanings inferred from the PDF text layer (Top Fig, early/late pace figures, running style).
  The Pace Projector order is **not** recoverable from the text layer: the digits come out line by line across the
  graphic, and the order the reader first claimed matched the charts' first-call leader in 0 of 15 races
  (2026-11-20). The reader now keeps the digits only as `pace_projector_digits` and claims no order.
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

## Phase D note: what changed in the suggestions, and what did not

Picks, scores, ranks and win probabilities are unchanged. The suggested wagers change where the decisions
table says (`handicapper/policy.py`, `wager_policy` in `rules_config.json`): no exotics in lone-speed races; on
turf win bets only (place and show candidates stay); no doubles through firm turf (morning condition from the
Equibase page); no trifecta or superfecta outside high confidence (medium: exacta box only; contentious: the
four-horse box is dropped); nothing the Equibase page says the track will not sell. Every suppression is kept on
the race (`policy.suppressed` with its reason) and shown as a POLICY line; the high-confidence trifecta keys,
doubles and Pick 3 / Pick 4 (tracked) are untouched.

Price: a win bet needs `O_min = (1 + tau + costs - rebate) / p - 1` with `tau` 0.15 (`pricing` block), which is
0.15 higher than the old fair x 1.15 at every probability (p = 1/3: 2.45-1 instead of 2.3-1); the break-even
odds `1/p - 1` are shown beside it. A few win bets near the old margin will now be "no win bet" lines.

Place and show: every race names one place and one show candidate from the Harville expansion of the blended
win vector (labelled heuristic), with a minimum $2 price `2 x (1 + place_show_tau) / p` rounded up to the dime;
they are suggested wagers at the configured $2 unit, settled against the chart's place and show prices, with a
four-or-fewer-starter field's missing show pool reported as not offered, and roll up as their own bet types.

Research layer (`research` on each race, `research` on each wager, `research` on each sheet row): model status
`UNTRAINED`; `p_rule_heuristic` over betting interests with a floor for eliminated starters; `q_live_market` from
the latest stored tote board when open, reconciled and fresh (else the reason); `p_market_anchor` with alpha 1,
beta 0 (the market, tote or renormalised morning line, labelled); EV at the quote, after an adverse drift and at
break-even as research diagnostics. While the model is not `VALIDATED` every single-horse wager is `NO_BET`
(`UNTRAINED_MODEL`, plus whatever else fails) and exotics and multi-race tickets are `candidate, unpriced`.
The legacy analysis keeps counting suggested bets as the owner decided; the research layer never changes it.

## Phase E note: what the 217 races say (and do not say)

`python -m handicapper.evaluation report --write` scores the pre-race predictions on file (217 races, 23 cards,
11/07 to 11/15; 4 made before the race's cutoff, 213 after) against the charts. Races are the unit.

- Log loss (floor 0.001): morning line renormalised 1.797 on the 139 races where every runner had one; rule
  heuristic 1.966; the printed blend 1.873; the final-odds market 1.696 (hindsight). Uniform would be about 2.0.
  The 95% intervals overlap widely: with 217 races nothing here separates the vectors with confidence.
- Reliability: the heuristic is over-confident at the top (horses it gives 60-100% win 45%; 40-60% win 32%) and
  under-confident at the bottom (0-5% win 4.7%, 5-10% win 13%). The blend is closer; the morning line is close
  to calibrated in every bin.
- Candidate blends on a chronological split (69 early races to choose, 70 late races to report): every weight
  above the configured 0.35 scored better on both halves; the weight chosen on the early half (1.0, the morning
  line alone) gives 1.773 on the late half, 0.65 gives 1.749. This is a research diagnostic: the configured blend
  is unchanged, because the global gate (300 races) is not met and 70 reporting races cannot carry the decision.
- Data watch: global calibration 217 of 300; track-specific at most 72 of 400 (CD); odds drift 0 of 150 (no
  tote history stored before Phase C); Timeform 0 of 200 (no Timeform file was merged into a run yet). Every
  deferred capability reads `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA`.

`docs/DATA_WATCH.md` and `docs/EVALUATION.md` are written by the command above and should be refreshed when
cards are added; the Analysis tab shows the same numbers live.

## Circuits (owner decision, 2026-11-16)

The data watch's second gate counts races per **circuit**, not per track: NYRA (BEL, SAR, AQU), SoCal (SA, DMR),
Kentucky (CD, KEE), Florida (GP); an unlisted track is its own circuit (`rules_config.json` -> `circuits`;
`data_watch.gates.track_specific.group` switches back to `track`). This is a pooling assumption the owner chose,
a judgement that those tracks share a horse population, trainer and jockey colonies and condition books; it is
not a statistical result, and the gate row says so. The four points the owner agreed:

1. One global model is validated first (the 300-race gate). Nothing below it is fitted before that.
2. When the gate is met, circuit effects come before track effects, as random effects shrunk toward the level
   above (`handicapper/deferred.py` documents the hierarchy global -> circuit -> track). Never a separate fit per
   circuit or track: with 50 to 70 races per track those would be noise.
3. Surface and distance splits come first in the evaluation (they lead the breakdowns in `docs/EVALUATION.md`),
   because the frozen week's turf / dirt gap is larger than any track difference. Distance is read from the
   race's distance text (sprint under 8 furlongs, route 8 and over).
4. The circuit gate reaches 400 sooner than a track gate would; the status doc and the Desk label it as pooling.

## Data on file (2026-11-15)

25 cards with picks, 157 snapshots, 25 results files; 219 races with pre-race snapshots and chart results;
79 races with a Timeform comparison; 0 tote observations.
