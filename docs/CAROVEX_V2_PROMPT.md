# Carovex Racing Engine V2 — implementation prompt (revised 2026-11-14, owner additions included)

## Your role

You are a principal Python engineer and quantitative horse-racing analyst working on an existing, working
application: `https://github.com/cocheuno/RulesBasedHRWager.git`. You evolve it in place. You do not rewrite it,
replace its UI, remove its rule library, or change what it recommends unless a phase below says so explicitly.

The owner is one person who runs four tracks a day from a Windows 11 / PowerShell machine with the local Race
Day Desk app. They can only sometimes bet in the last minutes before post. They cannot buy historical data, so
every statistical capability waits for the prospective data this system accumulates, and the system must say,
at all times, how far it is from having enough.

## Ground rules

1. **Nothing starts until the rule freeze ends.** The engine on `main` is frozen until the owner's review of the
   week ending 2026-11-15 is complete and they say so. Until then you may read, audit and write documents only.
2. **One phase is one pull request against `main`, merged before the next phase starts.** Never stack PRs.
   Never merge into a feature branch. Each PR body carries: the feedback item it answers, the files changed,
   the verification commands with their output, the judgement calls, and what changed in prediction or wager
   behaviour (ideally "nothing").
3. **Audit the checkout you have, not this document.** `main` has moved since any review. Record the Git SHA
   and Python version first. Cite real files and lines.
4. **Do not rebuild what exists.** Section "Already in place" lists it. Extend it.
5. **Decisions the owner has already made stand** unless they change them: unit stakes per bet type; exotics
   and daily doubles count as bets placed; Pick 3 / Pick 4 tickets are built and shown but tracked, not counted,
   until they have a record; trifectas key the standout first *or* second, four-horse box in medium and
   contentious races; hard eliminations (X rules) stay hard for selection, with a small floor only in the
   probability vector used for pricing and evaluation; a win bet needs a stated minimum price; **every race
   also names at least one place candidate and one show candidate** (Phase D).
6. **No proprietary files in the repository.** Brisnet PPs, Power Play sheets, TimeformUS PPs, Equibase pages,
   raw tote payloads and API keys stay under ignored paths (`data/pps`, `data/private`) or environment
   variables. Fixtures for tests are synthetic or trimmed public data (scratches, charts), as today.
7. **No real-money execution, ever.** Decisions are `suggested`, `paper`, or `accepted (verified by the owner)`.
   A suggestion never becomes an executed bet on its own.
8. **No hindsight.** A decision for race R at time T uses only information with `available_at <= T`, and T
   must be before R's wagering cutoff. A missing result file is not evidence that a race has not been run.
9. **No model fitting before the data gate in Phase E says so.** No LightGBM, no calibration fits, no
   odds-drift models, no track-specific refits. Build the interfaces, the capture and the gate.
10. **Dependencies:** standard library and `pdfplumber`, plus SQLite from the standard library for the ledger,
    plus `python-weather` for track weather (Phase B; optional at runtime, replayed in tests). Anything else
    needs a one-line justification in the PR and must be optional for the live path.
11. **Tests:** `python -m unittest discover -s tests -v` must pass at every commit. Every phase adds offline,
    deterministic tests. Report pre-existing failures separately from anything you introduce.

## Already in place (verify, then build on; do not rebuild)

- Brisnet Ultimate PP parser (`brisnet_pp/parser.py`), Power Play quick sheet (`brisnet_pp/sheet.py`), Equibase
  chart reader (`brisnet_pp/chart.py`), Equibase race-day-changes page reader (`brisnet_pp/changes.py`).
- Rule engine with pure rules and expert bases (`handicapper/rules.py`, `features.py`, `engine.py`), track
  profiles layered in `rules_config.json`, configuration validation at load.
- One probability module (`handicapper/probability.py`): softmax of the ability score blended with the
  morning line; value (V1) reported beside the score, never in it. Heuristic constants, labelled as such.
- Also-eligibles and MTOs outside the active field, scored conditionally; official draw-in tokens `r:+p`, `r:-p`.
- Wagering (`handicapper/wagering.py`): unit stakes per type, minimum win price, "passed at the window" when
  the chart's final odds are under the minimum (an *assumed-price* proxy, see Phase A), "not offered" when a
  chart lists no pool, Pick 3/4 tracked outside totals, identity check of results against the card.
- Append-only snapshots (`handicapper/snapshot.py`) with a run block: UTC time, scratches, parser version,
  config hash, git version, source hashes, races with results on file, Equibase changes summary.
- Race Day Desk (`ui/`): load, run, scratches, charts, process, analysis; stale-code banner; PP-upload guard.
- A working **TimeformUS PP text reader** exists as a prototype outside the repository
  (`tfus_read.py`: horse blocks, program, name, ML, Top Fig, last figures, running style with early/late pace
  figures; races split on program numbers restarting at 1). Four sample TimeformUS PDFs are in the owner's
  local `data/pps`. Move the reader into `timeform_pp/` in Phase B; do not write a JSON import format instead.

## Phase A — timing and the decision ledger

Goal: a prediction is "pre-race" per race, by the clock, not per card by the absence of results.

- **Cutoffs.** Read each race's scheduled post time from the PP header (the parser already keeps it as text)
  and convert it with a track-timezone table in `rules_config.json` (`tracks.<code>.timezone`). The Equibase
  changes page gives the first post as a cross-check. A run's status is computed per race:
  `before-cutoff` (run time < post time minus a configurable margin, default 2 minutes), `after-cutoff`, or
  `unknown` when the card has no post times. Never ask the owner to type post times.
- **Scoring.** The back-test and the Analysis screen score, for each race, the latest snapshot that is
  `before-cutoff` for that race. A card can therefore be scored from several snapshots. Legacy snapshots with
  no post-time evidence are scored as today but labelled `timing: unverified`.
- **Assumed price.** Keep the final-odds check, but label every price-gated row `price_basis: assumed-final`
  and keep the owner's ability to record `price_basis: observed` when a live quote (Phase C) was captured at
  decision time. For cards with no decision-time price and no final odds, mark `NOT_RECONSTRUCTABLE`; keep
  the horse-picking diagnostics; never invent a return.
- **Decision records.** Extend the run block rather than inventing a parallel store: each wager in a snapshot
  gets a stable decision id, decision time, cutoff status, price basis, status (`suggested` by default),
  model/config/parser hashes. A later run creates new records; it never edits earlier ones.
- **Ledger.** SQLite at `data/private/carovex.db` (ignored), versioned migrations, WAL, foreign keys. Tables:
  `race`, `betting_interest`, `source_observation`, `forecast`, `decision`, `execution`, `settlement`. Legacy
  JSON stays the source of truth for picks and results; the ledger indexes them and holds what JSON cannot
  (tote observations, decision histories). Provide import of existing snapshots and results, idempotent.
- **Tests.** (i) two races on one card have different cutoffs; (ii) a result entered after a decision cannot
  change it; (iii) final odds cannot turn an `accepted` decision into a pass; (iv) a snapshot after post is
  excluded for that race even with no result file; (v) reruns never overwrite prior decisions; (vi) legacy
  cards score as `timing: unverified`, not as pre-race.

## Phase B — all the data from every form, with provenance

Goal: every field the owner pays for is read, kept with its source, and available to rules; nothing is
awarded points because several vendors repeat the same signal.

- **Brisnet Ultimate PP.** Audit `features.py` against the parser's output and list every parsed field the
  rules do not read. Expose raw and derived values separately with source and date; running lines carry their
  own dates, and a feature vector as of time T contains no line or work dated after T. Add missingness flags.
- **Power Play sheet.** Keep every angle and rank the sheet prints as a typed feature with its original label,
  not only the key-race angles the rules use today. No new points; the back-test reports each angle's
  prospective hit rate so the owner can decide later.
- **TimeformUS.** `timeform_pp/reader.py` from the prototype, with a fixture built from a trimmed, anonymised
  sample and tests for: three-digit figures, first-time starters with no figure, race splitting, program
  letters (1A). Fields: pace-adjusted speed figure (top and per line), early and late pace figures, running
  style, Pace Projector order where the text layer allows it, ML. Store under its own namespace; never
  substitute a Brisnet value for a missing Timeform value or the reverse. The Desk gets a drop zone for the
  Timeform PDF beside the Brisnet one, with the same card-identity guard. The report and Desk show, per race,
  Brisnet rank and Timeform rank side by side; rules do not read Timeform until Phase E's comparison says
  they should.
- **Equibase changes.** Already read. Add the morning track condition and the pools-not-offered list to the
  inputs rules may read once the freeze ends (off-track rule; suppress a suggestion the track will not sell).
- **Weather.** Use the `python-weather` package to fetch the forecast for the track's location at each race's
  post time when a card is run, and store it as a `source_observation` (provider, fetch time, forecast time,
  condition, wind direction and speed, temperature, humidity, precipitation). Track locations live in
  `rules_config.json` (`tracks.<code>.location`). The fetch is optional: no network means `weather: unavailable`,
  never a guess, and tests use a replay fixture. The owner can also type the weather for the selected card
  into a text box (Phase F); typed weather is a second observation with provenance `manual`, it does not
  overwrite the fetched one, and the most recent observation before a race's cutoff is the one a rule may read.
  Rules do not read weather until the freeze ends and the owner approves a rule that uses it.
- **Canonical identity.** One mapping of track codes, dates, race numbers and betting interests across
  Brisnet, Timeform, Equibase and the tote provider, with coupled entries (1 and 1A are one interest) and
  program/post changes handled deterministically; ambiguous name matches go to a review list, never silently.
- **Tests.** Reconciliation across the four sources for one synthetic card: aliases, coupled interests, a
  duplicate horse name, a program change, a scratch, a surface switch, a partial Timeform file.

## Phase C — live odds and the tote board (PuntersEdge)

Goal: capture the US tote for every race the owner runs, show it live, and support a last-minute wager
check when the owner is present. The feed is cheap and the owner wants it.

- **Provider interface** `ToteProvider` with `PuntersEdgeProvider` (key from `PUNTERSEDGE_API_KEY`, `X-API-Key`,
  persistent session, timeouts, bounded retries, `Retry-After` on 429, gzip, redacted logs) and
  `ReplayToteProvider` (recorded synthetic responses, simulated clock, no key, no network). Read the current
  OpenAPI schema at `https://api.puntersedge.online/openapi.json` and the docs before coding any field name;
  do not guess keys. Never use a bookmaker endpoint as the tote.
- **Capture.** Every changed board is stored as a `source_observation` with provider read time and local
  receipt time, immutable, plus periodic heartbeats when unchanged. Win pool dollars per interest, displayed
  odds, total pool, scratches, status flags (open, closed, off, official), exotic probables and will-pays
  where the plan supplies them. `win_odds` may be null before pools open; morning-line values are never
  labelled as a tote quote.
- **Polling policy**, configurable with a daily credit cap: sparse until 15 minutes to post, about every 60
  seconds from 15 to 5, about every 30 in the last 5, stop at off/closed/official, fetch the final board and
  result afterwards. Track usage from response headers where available. A feed failure disables decisions
  and shows status; it never crashes the app.
- **Public allocation.** `q_i = W_i / sum W_j` over the validated active interests, reconciled with the
  provider's pool total and checked against normalised inverse odds. Keep the provider's odds convention
  (net to-1 or gross multiple) explicit. No second takeout deduction on displayed pari-mutuel prices.
- **Last-minute mode.** When the owner opens a race within the polling window, the Desk shows the engine's
  minimum price beside the current quote and freshness, and the decision record for that wager can be marked
  `paper` (owner intends) or `accepted (verified)` (owner placed it elsewhere and says so), with the quote
  snapshot id attached. That is the only way `price_basis: observed` is ever set.
- **Commands.** `python -m carovex.tote sample`, `poll <card> <race>`, `replay <fixture>`, `result <race>`;
  a local API endpoint to refresh one race.
- **Tests.** Normalisation with open and closed pools; coupled entries; late scratch; request failure, rate
  limit, stale data, missing odds, malformed numbers, pool-total mismatch; net vs gross odds; a credential
  never appears in a log or fixture.

## Phase D — market-aware research probabilities and explicit NO_BET

Goal: separate what the engine thinks, what the public thinks, and what would be a bet, without claiming
any of it is calibrated yet.

- Outputs per interest: `p_rule_heuristic` (today's softmax, labelled heuristic), `q_live_market` (Phase C,
  when validated), `p_market_anchor` with `p_i ∝ q_i^alpha · exp(beta · z_i)`, default `alpha=1, beta=0`
  (market only) and `z_i` a documented standardised score from the engine; `p_final_model` only once Phase E
  validates one. Model status `UNTRAINED | RESEARCH_ONLY | VALIDATED`, always shown.
- Probability vectors are over betting interests, finite, non-negative, sum to one. Every legal starter has
  positive mass in the research vector; eliminations remain hard for *selection* as the owner decided, and
  their pool share is never silently re-normalised away.
- **EV and price.** `EV = p·(O+1) − 1` per dollar at fixed net odds; required odds for a target return
  `tau`: `O_min = (1 + tau + costs − rebate)/p − 1`. Replace the current "fair odds × 1.15" with this formula
  and a documented `tau`; show break-even odds. Under pari-mutuel uncertainty show a current-quote scenario,
  an adverse-drift scenario and the break-even, labelled research diagnostics.
- **NO_BET reason codes**: stale data, unmatched runner, scratch or coupled-entry mismatch, market closed,
  untrained model, no validated edge, insufficient price, pool uncertainty, bankroll cap, invalid vector,
  unpriced exotic pool. A paper `BET` is recorded only when every configured gate passes; an `EXPERIMENTAL`
  flag exists for the owner's exploratory paper trades and is never confused with validated EV.
- Exotics and multi-race tickets keep being generated and, per the owner's policy, counted as suggested bets
  in the legacy analysis; the research layer labels them `candidate, unpriced`.
- **Place and show.** Every race names at least one place candidate and one show candidate, each with a
  minimum price. Candidates come from the race's probability vector with a documented heuristic for the
  chance of finishing in the first two and the first three (a Harville-style expansion of the win vector,
  labelled heuristic until Phase E validates it); the natural first candidate is the top pick when its win price
  fails, and a second horse when the top pick is already a win bet. Unit stakes for place and show are already
  configured at $2. Evaluation settles them against the chart's place and show prices, handles fields where the
  show pool is not offered, and reports them as their own bet types in the roll-up.

## Phase E — prospective evaluation and the data watch

Goal: measure honestly, say how far we are from being able to fit anything, and never fit on the races
used to evaluate.

- Race-level multiclass log loss with a documented floor, Brier score, reliability bins with counts, by
  field size, track, surface, condition and pace shape; prediction-to-final-odds differences; coverage and
  freshness. Compare: public market baseline, rule heuristic, and candidate blends, on pre-cutoff snapshots.
- Report races, not bets, as the sample size; confidence intervals; chronological splits only.
- **Data gate.** A `docs/DATA_WATCH.md` and an Analysis panel showing current counts against stated
  thresholds: global calibration pass of the softmax scale and blend needs 300 pre-cutoff races with results;
  a track-specific anything needs 400 races at that track; a late-odds drift model needs 150 races with
  complete tote histories; Timeform's incremental value needs 200 races with both figure sets. Thresholds are
  proposals; the owner can change them, the code cannot. Until a gate is met its capability stays
  `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA`, visibly.
- Interfaces and documentation for the deferred models: hierarchical figure correction, conditional-logit
  race model, odds-drift forecast, constrained Kelly, joint finishing-order exotic pricing.

## Phase F — Race Day Desk additions (additive only)

- **Weather entry.** On the selected race card, a text box that accepts the weather exactly as the track and
  Equibase pages print it, for example:

  ```
  Light Rain
  Wind NW at 13 mph	Temperature 44°F
  Humidity 82%
  ```

  Parse condition, wind direction, wind speed, temperature and humidity from that layout (tabs or spaces,
  any line order), store it as a manual weather observation (Phase B), and show the parsed values beside the
  fetched forecast so a disagreement is visible.
- **Scratch box toggles.** Ticking a horse and then unticking it must leave the Desk in the state it was in
  before: compare the current scratch set with the set the last run was made with, and show "re-run" only when
  they differ. The saved scratch list follows the same rule.
- **Plain English on every horse.** Everything the Desk and the reports say about a horse, the Top Reasons
  column, rule notes, audit lines, wager lines and chips, is written in ASD-STE100 Simplified Technical
  English: short sentences, one idea per sentence, active voice, approved words, no unexplained acronyms. Keep
  the rule ids as a reference in brackets at the end of a note, but say the thing in words first: not
  "S1 +6 top last-race fig", but "Ran the fastest speed figure in the field last time (S1, +6)". Expand every
  abbreviation the first time it appears on a screen: E1, E2 and LP become early pace, second-call pace and late
  pace; ML becomes morning line; ITM becomes in the money; AE and MTO become also-eligible and main-track-only.
  Add `docs/GLOSSARY.md` and a test that no horse-facing string contains an abbreviation from the glossary's
  list without its expansion. Rewrite rule docstrings' user-facing notes in the same style; the Basis sentences
  stay as they are.

A **Market** view per race: source coverage and parse status; morning line in its own column; current tote
odds, pool dollars, public allocation, provider read time and age; rule rank with audit, heuristic
probability, market probability, model probability if any; current-quote and break-even diagnostics; NO_BET
reason; odds and pool time series; scratches and coupled entries; the frozen decision record with its status.
Stale and unavailable are shown as such, never as current. Existing screens are not removed. Windows 11 /
PowerShell setup documented, `.env.example` with placeholders.

## Tests across phases (offline, deterministic)

Provider replay open and closed; identity edge cases; failure modes; odds conventions; probability simplex
and positive mass for a low-rated starter; before-off vs after-off; final odds never deciding placement;
immutable histories and idempotent ingestion; every existing parser, rule, scratch, multi-race, result, CLI
and UI test; no authorization on missing or invalid price; as-of feature causality; no credential or
proprietary content in logs or fixtures. One synthetic end-to-end run: two mock cards, reconcile, replay
several tote states, freeze paper decisions, close, ingest results, evaluate without hindsight, show the
Analysis JSON.

## Deliverables per phase

Changed files and design decisions; migrations and tests; the verification run; prior behaviour preserved;
`docs/CAROVEX_V2_ARCHITECTURE.md` (Phase A, then kept current) and `docs/CAROVEX_V2_IMPLEMENTATION_STATUS.md`
(implemented / tested / deferred / blocked, with the exact sample or key each blocked item needs). Commit in
focused commits; open the PR; stop and wait for the owner to merge before the next phase.

## Definition of done

The rule-based program still operates and its tests pass. Every prediction is timestamped per race against
its cutoff and cannot be changed by later odds or results. The tote adapter runs from the owner's key with
offline replay, a credit cap and honest freshness. Brisnet, Power Play, TimeformUS and Equibase inputs are all
read, kept with provenance, and shown side by side; rules read only what the owner has approved. Heuristic
probabilities cannot be mistaken for calibrated or live. Recommendations default to suggested or paper and
fail to NO_BET when data or validation is missing. The data watch says, in races, how far each deferred
capability is from its gate.
