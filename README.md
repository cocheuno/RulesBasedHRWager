# Brisnet Ultimate PPs → rules-based selections

Deterministic, auditable pipeline: **PDF → structured JSON → scored rule hits → 1–3 horses per race.**
No cloud services, no ML; every point on a horse's scoresheet is traceable to a named rule
with a one-line justification.

```
pip install pdfplumber              # the only dependency (poppler not required)
pip install rapidocr_onnxruntime    # optional: reads the result screenshots (pure pip, no system install)

python pick.py dmr1106y.pdf                         # parse + score, print the report (wagering summary first, then details)
python pick.py dmr1106y.pdf --detail 0              # wagering summary only: top 3 per race, primary play, other wagers, Pick 3/4 tickets
python pick.py dmr1106y.pdf -o out/                 # also write <card>.card.json / .picks.json / .picks.md
python pick.py out/dmr1106y.card.json --race 4 --detail 2    # full rule-by-rule audit, one race
python pick.py --rules-doc > RULES.md               # regenerate the rule catalog
python pick.py out/dmr1106y.card.json --budget4 48  # Pick 3 / Pick 4 tickets shaped to a budget (--no-multi to skip)
python -m brisnet_pp.parser dmr1106y.pdf -o card.json        # parser only
python validate_parse.py card.json                  # internal consistency checks on a parsed card
python pick.py dmr1106y.pdf --scratch "3:3, 8:4, 8:9"             # remove scratches (also-eligibles draw in), re-rank
python pick.py dmr1106y.pdf --results results/dmr1106y.results.json   # earlier races' winners feed the same-day bias rule P10
python backtest.py out/dmr1106y.picks.json results/dmr1106y.results.json   # join picks with results: per-race and per-rule hit rates
python ui.py start                                  # Race Day Desk in the background (http://127.0.0.1:8765); ui.py stop / status
python ocr_results.py data/results-png/dmr1106y results/dmr1106y.results.json --card data/out/dmr1106y.card.json   # screenshots -> results
python -m unittest discover -s tests -v             # rule + Pick 3/4 tests on a synthetic card (no real data needed)
```

Day-to-day commands: see **[RACE-DAY.md](RACE-DAY.md)**.

## Layout

```
brisnet_pp/
  symbols.py     decoding of Brisnet's PP2B symbol font (superscripts, fractions, race symbols)
  parser.py      coordinate-based PDF parser -> dict/JSON (races, horses, PP lines, workouts,
                 race summary table, track-bias stats, ranking boxes)
handicapper/
  features.py    per-horse derived features + field-relative ranks + pace scenario
  rules.py       the rule catalog (72 rules, each a pure function with its definition and expert basis in the docstring)
  multirace.py   Pick 3 / Pick 4 construction (9 H-rules: singles, A/B coverage, vulnerable favourites, tickets, budget)
  engine.py      scoring, value overlay, selection policy, markdown report
tests/
  synthetic_card.py   invented card in parser output shape (no proprietary data) used by the tests
  test_rules.py, test_multirace.py
pick.py          CLI
rules_config.json   weight overrides / disabled rules / selection thresholds (versioned governance)
validate_parse.py   parser self-checks
RULES.md         generated rule catalog
```

## How the parser works

The Brisnet PDF is a fixed 612×792 grid and every column of the past-performance table
sits at the same x-coordinate on every page (verified across all 77 headers on this card).
The parser therefore reads **character coordinates** with `pdfplumber`, groups characters
into rows by `top`, and slices each row into columns by `x0`. Nothing depends on text
extraction heuristics, so kerning artefacts ("1:43ª¦¨¨©™MC62500/50") do not matter.

Brisnet's symbol font (decoded empirically and cross-checked against finisher margins):

| glyphs | meaning |
|---|---|
| `§ ¨ © ª « ¬ ­ ® ¯ °` | superscript digits 0–9 (race number, lengths, jockey weight, race/class ratings) |
| `\x81  ‚  ƒ` | ¼ ½ ¾ lengths |
| `± ² ³ ´` | neck, head, nose, dead-heat |
| `ˆ „ ‰ ‚` after a mile count | 1/16, 1/8, 3/16, 1/2 mile (`1ˆ` = 1 1/16 mi) |
| `à` / `Ì` / none | turf / all-weather / dirt; `*` = about-distance or alternate (hillside) course |
| `¦` / `¡` / none | race was for 3&up / 4&up / age-restricted |
| `™` `‘` | fillies-mares race, state-bred race |
| `ñ` / `×` | positive / negative QuickPlay comment (× before a workout date = bullet work) |
| `È` | first-time Lasix; `L b f` after jockey = Lasix, blinkers, front wraps |
| `*` after jockey weight | apprentice allowance; `*` before odds = favourite; `e` after odds = coupled entry |
| `11pp10` in the program-number cell | program 11, post 10 (after scratches); `AE`/`MTO` = also-eligible / main-track-only |

Three-superscript distances (`¯®§`) are yards (870y Quarter-Horse-style races at Los Alamitos).

### Output model (abridged)

```
card: {track, date, races: [race]}
race: {race_no, class_text, class_code (MCL/MSW/MOC/CLM/OC/ALW/STK/HCP/STR), claiming_price,
       distance_furlongs, surface, is_route, purse, conditions, pars{e1,e2,late,speed},
       top3{speed_last_race, prime_power, class_rating, best_speed_at_dist},
       racetype_stats, bias{meet, week}{runstyle{E,E/P,P,S}{impact,win_pct,marks}, post{...}},
       summary[...], rankings{...}, horses: [horse]}
horse: {pgm, post, entry_status, ml_odds, ml_decimal, name, run_style, speed_pts, claim_price,
        color, sex, age, foal_month, sale, prime_power, prime_power_rank, owner, sire, dam, dam_sire,
        breeder, bred_state, trainer, trainer_meet, jockey, jockey_meet, weight, apprentice_allowance,
        lasix, first_lasix, blinkers_change, records{life, year_YYYY, track, fst, off, dis, trf, aw},
        pedigree_ratings{fst,off,dis,trf}, jockey_stats[], trainer_stats[{category, flag, starts, win_pct, itm_pct, roi}],
        pedigree_stats{sire, dam_sire, dam, sold_at}, positives[], negatives[], days_since_last,
        summary{...race-summary row...}, pp: [pp], workouts: [work]}
pp:    {date, track, race_no, foreign, surface, distance_furlongs, distance_text, track_condition,
        fractions[], final_time, age_restriction, race_rating, race_type, class_code, claimed,
        race_purse_or_price, class_rating, e1, e2, lp, c1, c2, speed, post,
        start/call1/call2/stretch/finish{pos, lengths, margin}, jockey, weight, apprentice,
        lasix, blinkers, front_wraps, favorite, odds, coupled_entry, field_size,
        top_finishers[{name, margin_lengths}], comment, finish_pos, beaten_lengths, won, dnf, is_route}
```

Validation on this card: 8 races, 79 entries, 574 running lines, 923 workouts; all header
boxes (Prime Power, speed-last-race, class) reconcile with the per-horse data; 0 hard failures.

## How the rules work

`rules.py` registers every rule with `@rule(id, name, category, weight)`.  A rule returns
`None` (no opinion) or `(factor, note)`; the engine adds `factor × weight` to the horse and
keeps the note.  Hard rules (`X*`) eliminate (negative factor) or flag (AE/MTO).  The score is a pure
*ability* score.  `handicapper/probability.py` turns it into the one win probability every report and every
Pick 3/4 leg reads (softmax of the score, blended with the morning line); `V1` compares the engine's fair odds
from that model with the morning line and is reported as *value* beside the score, never added to it, so a
horse's rank does not move because its price is generous or short.  Eliminated horses have probability 0 for
selection; only when a Pick 3/4 ticket is priced does each keep a 2% floor (`elim_floor`).

Categories: **S** speed · **C** class · **P** pace & bias · **F** form · **K** connections ·
**D** distance/surface · **E** equipment · **Q** QuickPlay comments · **M** maidens ·
**A** age/weight · **X** eliminations · **V** value · **H** horizontal (Pick 3 / Pick 4).  See `RULES.md`.

### Expert basis

Every rule's docstring ends with a **Basis:** sentence naming the published handicapping practice it encodes
(Beyer on figures, pairing, bounce and trips; Brohamer on E1/E2/LP pace matchups; Quirin on early speed and
impact values; Davidowitz on class drops, claimed horses, beaten favourites and trainer intent; Quinn on the
condition book; Litfin on form cycles; Meadow and Crist on odds lines and multi-race tickets; Brisnet's own
Prime Power / run-style FAQs).  The weights are set so that the primary factors (speed, class, pace, form)
decide and the composites (Prime Power, QuickPlay comments) only break ties, because the composites already
contain the primary factors.

How the PPs *with comments* are read: the running-line comment is the only trip note on the page, so it is used
across the last three races (F3, F11 trouble; F12 pace pressure; F13 beaten-favourite excuses; F1 manner of
victory), and Brisnet's QuickPlay bullets are scored lightly (Q1/Q2) as a cross-check.

### Pick 3 / Pick 4 (`handicapper/multirace.py`)

After every race is scored, each leg's live horses get a blended win probability (rules-engine softmax blended
35/65 with the morning line, H1) and are graded Crist-style:

* **single** (H2) only when the top horse has >= 45% and is 7+ points clear and carries no bounce / duel /
  underlay / suspicious-drop hit - a short-priced single is still a single, the saving buys coverage elsewhere;
* **chaos legs** (H3: 4+ horses within 4 points, or 10+ runners with no horse over 25%) get wider coverage;
* otherwise A horses until 55% of the leg is covered, B horses until 78% (H4);
* the ML favourite is demoted to a B when it is beatable (H5) - that leg becomes the *price leg*;
* also-eligibles and X-eliminated horses are never on a ticket (H6);
* tickets are the main (all A) plus one "A's with one B" backup per leg (H7), trimmed to the budget by dropping
  the weakest B's first (H8);
* every consecutive window on the card is costed and ranked by hit probability x (1 + 0.25 x singles) x
  (1 + 0.35 x price legs); the ML parlay of the shortest A's is printed as a will-pay yardstick (H9).

Budgets, coverage targets and thresholds are in `rules_config.json -> multirace`; `--budget3/--budget4` override
the budgets from the command line and `--no-multi` suppresses the section.

### Other wagers per race (`engine.other_wagers`)

The wagering summary lists each race's top three ranked live horses (score, blended win chance, A/B grade) and a
set of secondary wagers chosen by the race's confidence: exacta and superfecta **keys** on a standout and two
trifecta tickets with it keyed first *or* second over the next three; exacta box plus part-wheel and a four-horse
trifecta box in a medium race; boxes only in a contentious one; WIN only on a V1 overlay, the favourite kept
underneath when H5 finds it beatable, and a daily
double with the next race's A horses.

Selection (`rules_config.json → selection`): the top horse is a **single** when it is
`single_gap` (7) points clear and the race is not contentious (fewer than 4 horses within
`spread_gap`); the 2nd is added when within `pair_gap` (4) or the race is contentious; a 3rd
when within `third_gap` (7).  Also-eligibles are never picked outright — they hold no rank among the
runners and are reported as "would rank N if it draws in".  ML ≤ 6/5 singles are keyed in exotics rather than
bet to win.

### Tuning

* Change a weight: `"weights": {"S7": 5, "P5": 2}`; switch a rule off: `"disabled": ["V1"]`.
* **Track profiles**: `"tracks": {"DMR": {"weights": {...}, "selection": {...}, "multirace": {...}}}` layers over
  the global values and is chosen automatically from the track code the parser reads off the PP (every horse's
  track-record line carries it); `"track_aliases"` maps track names to codes as a fallback, and
  `pick.py --track-profile SA` forces one.  The report header and `picks.json["track_profile"]` say which profile
  scored the card.  The rule logic is common to all tracks; what the profiles carry is how much each factor counts
  (pace rules P1/P3/P4/P7, course specialists D5/D6, post bias P6, trainer thresholds) and the ticket parameters
  (denominations, budgets, chaos-leg field size).  The shipped profiles are expert priors; fit them per track with
  `backtest.py` as cards accumulate.
* Every run writes `*.picks.json`, which contains the full per-horse feature set and every
  rule hit — join it with results to back-test weights.
* Add a rule: write a function in `rules.py` with the `@rule` decorator and a docstring ending in a
  `Basis:` sentence; it appears in the audit and in `RULES.md` automatically (the tests enforce the basis line).
* Pick 3/4 behaviour: `multirace` block in `rules_config.json` (budgets, `single_prob`, coverage targets,
  `fav_vulnerable_rules`); the probability model in the `probability` block (`logit_scale`, `ml_blend`, `elim_floor`).

## Race Day Desk (`python ui.py`)

The local screen for the whole day, on the Python standard library (no new dependency): `ui/server.py`
serves `ui/static/` at http://127.0.0.1:8765 and a JSON API that calls `handicapper.pipeline.run_card`, the
same function `pick.py` uses.  Three screens: **Desk** (card / race selection, the horses with program, post,
ML, rank, score, win chance, A/B grade and a scratch checkbox; Run / Re-run buttons; primary play, other wagers,
Pick 3/4 tickets; the rule-by-rule audit; after the race the finish, payoffs, screenshot and what every
suggested wager returned), **Load** (drop the PPs, the quick sheet and result PNGs; the scratch list; the runs
kept per card; an activity log) and **Analysis** (filters, KPIs, hit/miss bars per track and overall, tables
by bet type / track / confidence / rule / card, the Brisnet benchmark).  Design: `docs/UI-DESIGN.md`.
Per-card UI state lives in `data/cards/<card>.json` (ignored by git).

## Local data layout

PDFs and `*.card.json` never enter the repository.  Result screenshots (public payoff pages) and the engine's
`picks.json` do, so the after-race processing can be done from any clone:

```
RulesBasedHRWager/
  results/dmr1106y.results.json        committed: payoffs / finish order, transcribed from the screenshots
  results/dmr1106y.backtest.md         committed: the back-test report for that card
  data/
    pps/dmr1106y.pdf                   ignored: the TwinSpires / Brisnet download, named <trk><mmdd><y>.pdf
    results-png/dmr1106y/r1.png ...    committed: one payout-page screenshot per race, r<N>.png
    out/dmr1106y.picks.json            committed: pick.py -o data/out (card.json and picks.md stay ignored)
```

Before the races (local): `python pick.py data/pps/dmr1106y.pdf --scratch "..." -o data/out`.
After the races (local): save each payout page as `data/results-png/dmr1106y/r<N>.png`, then
`git add data/results-png data/out/*.picks.json`, commit, push.
Processing (from any clone): read the screenshots into `results/dmr1106y.results.json` (by hand or with
`addresult.py`), run `python backtest.py data/out/dmr1106y.picks.json results/dmr1106y.results.json > results/dmr1106y.backtest.md`,
commit `results/`.

## TimeformUS PPs (`--timeform <file>.pdf`)

`timeform_pp/reader.py` reads the TimeformUS PP through its text layer: Top Fig (pace-adjusted speed figure),
running style with early and late pace figures, ML, weight, every running line with its own date and figures, the
Power Picks and, when the graphic's digits come through in order, the Pace Projector. Values live under their own
namespace (`horse["timeform"]`, `race["timeform"]` with a rank by Top Fig) and are never substituted for a Brisnet
value or the reverse. The report and the Desk show `TF rk/fig` beside the Brisnet rank; no rule reads Timeform.
The Desk's Load tab takes the PDF beside the Brisnet one, with the same track-and-day guard.

## Measured angles: track condition and race type (`handicapper/angles.py`)

Two sets of labels per horse, scored in the back-test and in the Analysis tab's **Angles** panel (horses, wins,
in-the-money rate, flat $2 win return) and given **no points**:

- **Track condition**, when today's surface is off (wet dirt, or turf softer than firm): whether the horse has won,
  run in the money, or failed on an off surface of the same kind before, read from the condition code on every past
  line; on wet dirt also the sire's mud-winner rate and Brisnet's off-track pedigree rating. Today's condition is
  the Equibase morning condition; for older runs without one, the chart's condition at post time (the report says
  which).
- **Race type**, from Brisnet's statistics for this race type at this track: the morning-line favourite by how
  often favourites win this race type, and horses 10-1 or longer by the share of winners at 10-1 or more.

The Analysis panel also scores the cards already on file, computing the angles from each card's saved past
performances (pre-race data, so nothing leaks). `python -m handicapper.angles` prints the same table.

## Racing Dudes picks (`--racing-dudes <saved page>.html`)

`racing_dudes/reader.py` reads the Racing Dudes premium picks dashboard saved from the browser ("Webpage, HTML
only"): one page, every track on your list, a tab per race date. Per race it keeps their Win, Place, Show and
Next Best horses (program number, name, morning line, jockey, trainer), their exacta, trifecta and multi-race
structures, and the Likely Winner / Best Value tags. It is an expert opinion built from the same past
performances, so it is kept under its own namespace as a **benchmark**: shown beside the engine's rank on the Desk
and in the report, scored in the back-test ("their win pick won X of Y"), counted by the data watch
(`racing_dudes_value`, 200 races). No rule reads it. Drop the page once on the Load tab; it is saved as
`data/pps/racingdudes_<date>.html` for each date on the page and applied to every loaded card of those dates.

```
python -m racing_dudes.reader read <page.html>                 # tracks and race counts on the page
python -m racing_dudes.reader benchmark <page.html> [...]      # their picks against the results on file
```

The benchmark command also takes archive pages for past dates (unverified layout: the reader falls back to a
single-track page when it finds no track sections), which scores their published picks against the races already
on file without waiting weeks.

## Weather (`--weather`)

With `--weather` (the Desk does it on every run) the forecast for `tracks.<code>.location` is fetched with
`python-weather` and one observation per race post time is recorded on the run and on the race; without network
or a location the run says `weather: unavailable` with the reason, never a guess. Typed weather
(`POST /api/cards/<card>/weather`) is a second observation with provenance `manual`. No rule reads weather.

## Desk additions (Phase F)

Market view per race (source coverage, morning line, tote odds and pools with read time and age, rule rank,
heuristic and market probabilities, break-even and minimum odds, research gate, decision record, odds and pool
history); a weather text box whose parsed values sit beside the fetched forecast; scratch ticks compared with the
set the last run used ("re-run" only when they differ); a labelled **Best bets of the day** view
(`GET /api/best-bets?date=`); plain English on every horse-facing string (`handicapper/plain.py`,
`docs/GLOSSARY.md`, `tests/test_plain.py`): the note says the thing in words and the rule id follows in brackets.
`.env.example` lists the environment variables; `.env` is read at start and ignored by git. Windows 11 /
PowerShell set-up is in `RACE-DAY.md`.

## Picks sources against the engine (`handicapper/sources.py`)

The Analysis tab's **Picks sources against the engine, by bet type** panel settles Racing Dudes and Timeform on
money beside the engine. Racing Dudes' tickets are settled as published: $2 win, place and show on their Win pick,
their exacta and trifecta lines (box or part-wheel), and doubles and Pick 3 / Pick 4 built from their Multi Race
horses in consecutive races. Timeform publishes no tickets, so its Power Picks go into the engine's structures
(win on Power Pick 1, exacta box of 1-2, trifecta box of 1-3), labelled as built by us. The engine is scored on
exactly the same races from each card's pre-race prediction; scratched horses leave every ticket; Pick 3 / 4 are
tracked, not counted. `python -m handicapper.sources` prints the same table.

## Best bets of the day (`handicapper/bestbets.py`)

One rule serves the Desk strip and the record: the engine's suggested win bets ranked by expected value at the
morning line, top two per card. The record applies it to each card's pre-race prediction, so re-running a card
after the races cannot change it, and settles each bet at $2 against the chart: every best bet, and only those whose
final odds met the minimum price. It is on the Analysis tab, and `python -m handicapper.bestbets` prints it.

## Prospective evaluation and the data watch (Phase E)

```
python -m handicapper.evaluation report --write   # docs/EVALUATION.md: log loss, Brier, reliability, breakdowns, blends
python -m handicapper.evaluation watch --write    # docs/DATA_WATCH.md: race counts against the owner's gates
```

The unit is a race. Only pre-race predictions enter (the newest run made without the result, whatever the hour).
Three vectors are compared on the same races (the morning line renormalised, the rule heuristic, the printed
blend) with the final-odds market shown as hindsight; multiclass log loss with a documented floor, Brier score,
reliability bins with counts, breakdowns by field size, track, surface, condition, pace shape and clock, the mean
gap to the final odds, bootstrap and Wilson intervals. Candidate blend weights are looked at on the earlier half
of the races and reported on the later half; nothing is fitted on the races it is scored on and nothing is written
back to the configuration. Circuits (`rules_config.json` → `circuits`: NYRA, SoCal, Kentucky, Florida) are the owner's pooling assumption:
the second gate counts races per circuit, and the deferred models add circuit effects before track effects under
one global model. The data watch (`rules_config.json` → `data_watch.gates`) counts races against the
thresholds the owner set (300 global, 400 per track, 150 tote histories, 200 Timeform); until a gate is met the
capability reads `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA`, and `handicapper/deferred.py` refuses to fit. The
Analysis tab shows the same panel.

## Wager policy, price and the research layer (Phase D)

`handicapper/policy.py` applies the owner's decisions table (`rules_config.json` → `wager_policy`) to the
suggested wagers after they are built: no exotics in lone-speed races; turf win bets only; no doubles through firm
turf; no trifecta or superfecta outside high confidence (medium: exacta box only; contentious: the four-horse box
is dropped); nothing the Equibase page says the track will not sell. Every suppression is kept on the race with its
reason and shown as a POLICY line. Picks and scores never change.

A win bet needs `O_min = (1 + tau + costs - rebate) / p - 1` (`pricing`, tau 0.15); the break-even odds `1/p - 1`
are shown beside it. Every race names a place and a show candidate (Harville expansion of the win vector, labelled
heuristic) with a minimum $2 price; they are $2 wagers settled against the chart's place and show prices.

`handicapper/research.py` adds, per race and per wager, the research layer: `p_rule_heuristic`, `q_live_market`
(from the latest tote board), `p_market_anchor` (q^alpha · exp(beta·z), alpha 1, beta 0), `p_final_model` (none),
`model_status` (UNTRAINED until Phase E), EV at the quote / after an adverse drift / at break-even, and NO_BET
reason codes (stale data, unmatched runner, scratch or coupled mismatch, market closed, untrained model, no
validated edge, insufficient price, pool uncertainty, bankroll cap, invalid vector, unpriced exotic pool). While
the model is untrained every single-horse wager is NO_BET in that layer and exotics are "candidate, unpriced";
the legacy analysis still counts suggested bets as configured.

## Live odds and the tote board (`carovex/tote.py`)

PuntersEdge's `/v1/racing/tote` is TVG's public US board: one read returns every race of the day for 2 credits.
The key is read from `PUNTERSEDGE_API_KEY` or `data/private/puntersedge.key` (both outside git) and sent as
`X-API-Key`; it never appears in a log, an error or a fixture. Every changed board is stored as an immutable
`source_observation` (and as JSON under `data/private/tote/`), with the provider's read time and the local
receipt time; unchanged boards are stored as heartbeats every five minutes. A board carries, per betting
interest (1 and 1A are one interest), the WIN pool dollars, the displayed odds **to 1, net, as the track shows
them** (`win_decimal` is the gross multiple, nothing deducts a second takeout), the morning line (never labelled a
quote), scratches with reasons, the public allocation `q_i = W_i / ΣW_j` reconciled with the pool total and
checked against normalised inverse odds, and flags for anything malformed, missing or stale.

```
python -m carovex.tote sample                 # today's board: tracks, races, status, credits (2 credits)
python -m carovex.tote poll <card> [race]     # one read for the card's track; --loop follows the polling plan
python -m carovex.tote result <card> <race>   # final board with the odds history and exotics (2 credits)
python -m carovex.tote replay tests/fixtures/tote_replay.json
python -m carovex.tote usage                  # credits used / remaining (free)
```

Polling plan (`rules_config.json` → `tote.poll`): nothing until 60 minutes before post, then every 5 minutes,
every minute inside 15, every 30 seconds inside 5, stop at off / closed / official. `tote.daily_credit_cap`
bounds the spend per day; a feed failure (key, credits, rate limit, network) disables decision marks and shows
as a status, never a crash. On the Desk, **Refresh tote** on a race reads the board, the horses table gains a
Tote column, and the wagers list shows the engine's minimum price beside the current quote and its age. A
suggested wager can be marked **Paper** (you intend it) or **Accepted (verified)** (you placed it elsewhere and
say so); both freeze the quote snapshot id, and accepted is the only way a wager's price basis becomes
`observed`. Rules do not read the tote.

## Brisnet Power Play sheet (`--sheet <card>q.pdf`)

The quick sheet that accompanies the PPs is read coordinate-wise by `brisnet_pp/sheet.py`.  Only two things are
taken from it: each horse's Power Play angles, of which **"ExitKeyRace" / "ExitPossibleKeyRace"** feed rule F16
(the key-race angle the PPs alone cannot show), and Brisnet's own top pick / Top 3 / 3-Star Best Bets, which
`backtest.py` reports as a benchmark next to the engine's picks.  The other angles (hot trainer, distance
specialist, horse for course, clocker specials) restate data the PP rules already score and are ignored.

## Results, scratches and back-testing

* **Per-race timing** (`handicapper/timing.py`): every run records, for each race, whether it was made at least
  `timing.cutoff_margin_minutes` (2) before that race's cutoff: the chart's actual off time when a result is on
  file (track timezone from `tracks.<code>.timezone`), else the PP's scheduled post (the Eastern value of the
  four-zone post-time string).  The back-test and the Analysis screen score, race by race, the newest run that did
  not have that race's result on file (`snapshot.pre_race_by_race`), whatever the hour it was made: a late run
  uses only the PPs and the public scratches, so it is a pre-race prediction.  The clock status is recorded beside
  each race (before-cutoff / after-cutoff / unknown), never used to drop a run; only a race whose every run knew
  the result is excluded.  Every suggested wager carries a frozen `decision` record (id, time, cutoff status,
  price basis, status `suggested`).  Win-bet rows say their price basis: `assumed-final` (the chart's final odds
  decided whether the morning-line decision met its price), `unpriced`, or `observed` (an accepted decision,
  never passed by hindsight).
* **Ledger** (`carovex/ledger.py`): SQLite at `data/private/carovex.db` (ignored), versioned migrations, tables
  race / betting_interest / source_observation / forecast / decision / execution / settlement, append-only.
  `python -m carovex.ledger import .` indexes every snapshot and results file; `python -m carovex.ledger as-of . <card>
  <race> <UTC>` answers what was known at that time.
* **Snapshots** (`handicapper/snapshot.py`): every run is also frozen, append-only, as
  `data/out/snapshots/<card>/<UTC>_<kind>.picks.json` with a `run` block (UTC time, scratches, parser version,
  configuration hash, git version, source file hash, which races had results on file, odds source).  Kinds:
  `pre-race` (no result on file yet: the run you could bet from), `post-results`, `as-run` (the retrospective
  re-score with the chart's field).  `picks.json` stays the *latest* run.  The back-test and the Analysis screen
  score the newest pre-race snapshot and label the as-run numbers as retrospective; a card with no pre-race
  snapshot says so.
* `results/<card>.results.json` holds hand-transcribed payouts / finish order (format in `handicapper/results.py`).
  Results and payoffs are public data and may be committed; PPs are not.
* `--changes <file>`: Equibase's late-changes XML for the day (every track; `brisnet_pp/changes.py` →
  `parse_late_changes_xml`, this card's track picked out by Equibase id or name) or the saved per-track HTML page.
  Horse changes become "Scratched - reason" / "Jockey - A changed to B" lines, a surface change from turf adds an
  "Off Turf" note, a condition change fills the morning condition, a rail change the rail, a wager cancellation the
  pools not offered; every change is kept verbatim under `raw`. The Desk saves the XML once per date and applies it
  to every card of that date. The older form, a saved page (`.html`), adds that page's scratches to
  `--scratch` and records the morning track condition, scheduled first post, temporary rail, jockey changes,
  gelding / equipment notes and pools the track is not offering, on the run block and on each race.  Data only:
  no rule reads it yet.  The Desk takes the same file on the Load tab.  Each race carries the page's `inputs`
  (morning condition, off-turf, pools not offered, rail); a race the page takes **off the turf** is scored on
  `tracks.<code>.off_turf_surface` with its MTO entrants in, and `surface_switch` is recorded on the race and the run.
* `python -m handicapper.provenance audit <card.json>` lists the parser fields no rule reads; `horse_record` /
  `card_records` expose every value with source and date, missingness flags, and an as-of filter.
* `--scratch "r:p, r:p"` removes scratched horses before scoring; one also-eligible draws in per scratch, in
  program order (MTO horses stay flagged).  `r:+p` states that an AE/MTO is officially in (also when the race
  comes off the turf), `r:-p` that it stays out although a scratch would normally bring it in.  Pace shape and
  all field-relative ranks are recomputed over the active field only: an alternate that has not drawn in is in no
  denominator, no pace count and no probability; it is scored against a field that includes it and reported with
  the rank it *would* hold ("(4)").
* `--results` reads the same file and, for each race, summarises the winners of the earlier races on the same
  surface (run style, post) as `race["day_bias"]`, which rule **P10** scores once three such results exist.
* **Result charts are the best source.** The Equibase/Brisnet chart PDF (the track site's "View chart", e.g.
  `20261106BELUSA1.pdf`) is real text in the PP symbol font; `brisnet_pp/chart.py` reads it coordinate-wise: every
  finisher with program number, final odds, position and margin at every call, beaten lengths, equipment, weight,
  the track condition, times, pools, scratches and the trip comment per horse.  Drop charts in
  `data/results-png/<card>/` (as downloaded or as `r<N>.pdf`); a chart beats a screenshot of the same race.
* **Screenshots are read, not typed.** `handicapper/ocr.py` runs RapidOCR (optional `pip install rapidocr_onnxruntime`;
  Tesseract + `pytesseract` also works) on each `r<N>.png`, assigns win/place/show by column, takes the finish order
  from the exotic combinations (the "PP n" boxes are post positions), reads every pool line with its base and payout,
  skips consolation lines, and cross-checks the runner names against the card.  Anything doubtful is a warning stored
  under the race's `ocr` block; the Desk shows "Check this result" and keeps the entry form for corrections.
  Verified exact on all three Del Mar screenshots on file.
* `backtest.py` joins `picks.json` with results: winner's rank, top-pick hit rate, flat win-bet ROI, whether an
  eliminated horse won, per-rule win% / ITM% when the rule fired, and whether the recommended Pick 3/4 hit.
  This is the data the weights in `rules_config.json` should eventually be fitted on.
* **Wagering analysis** (`handicapper/wagering.py`, printed by `backtest.py`): every suggested wager (primary play,
  other wagers, recommended Pick 3/4 tickets) is a structure the engine emits beside its text; each is scored
  against the results file at a **unit stake per bet type** (`rules_config.json -> wagering.units`: $2 win/place/show,
  $1 exacta, $0.50 trifecta, $0.10 superfecta, $1 double; Pick 3 $1 and Pick 4 $0.50 from `multirace.pickN.base`,
  or the track menu's minimum when higher), overlapping suggestions are
  counted once, a win bet is **placed only if the chart's final odds meet the minimum price the engine asked for**
  (otherwise it is "passed at the window": no cost, not a bet), a pool that an official chart does not list was
  **not offered** by the track and the wager is reported as such (no cost, not a bet; the engine also suggests no
  trifecta under 5 starters and no superfecta under 7, `selection.min_field_trifecta/superfecta`), the recommended Pick 3 / Pick 4 tickets are
  evaluated and listed but **tracked, not counted** (`wagering.count_multirace`, off until the sequences have a
  measured hit rate; their hit probability is an estimate, the formula × `multirace.hit_prob_shrink`), and the
  roll-up gives bets / hits / misses / cost / return / ROI by bet type, track and confidence
  plus the hit-miss counts per track for the charts.  Pick 3/4 windows are only built where the PP's wager menu
  offers them, at the offered denomination (rule H10).

## Known limits

* Track condition is not in the PPs (an off track changes the meaning of several rules).
* Foreign (European / Meydan) lines carry no Brisnet figures; those horses are judged on
  class, comments and connections only (e.g. Tailgunner Joe, R6).
* The class ladder in `features.class_level` is calibrated for the Southern California
  circuit; adjust for other circuits.
* Weights are expert priors, not fitted; the audit trail exists precisely so they can be.
