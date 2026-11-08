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

## Brisnet Power Play sheet (`--sheet <card>q.pdf`)

The quick sheet that accompanies the PPs is read coordinate-wise by `brisnet_pp/sheet.py`.  Only two things are
taken from it: each horse's Power Play angles, of which **"ExitKeyRace" / "ExitPossibleKeyRace"** feed rule F16
(the key-race angle the PPs alone cannot show), and Brisnet's own top pick / Top 3 / 3-Star Best Bets, which
`backtest.py` reports as a benchmark next to the engine's picks.  The other angles (hot trainer, distance
specialist, horse for course, clocker specials) restate data the PP rules already score and are ignored.

## Results, scratches and back-testing

* **Snapshots** (`handicapper/snapshot.py`): every run is also frozen, append-only, as
  `data/out/snapshots/<card>/<UTC>_<kind>.picks.json` with a `run` block (UTC time, scratches, parser version,
  configuration hash, git version, source file hash, which races had results on file, odds source).  Kinds:
  `pre-race` (no result on file yet: the run you could bet from), `post-results`, `as-run` (the retrospective
  re-score with the chart's field).  `picks.json` stays the *latest* run.  The back-test and the Analysis screen
  score the newest pre-race snapshot and label the as-run numbers as retrospective; a card with no pre-race
  snapshot says so.
* `results/<card>.results.json` holds hand-transcribed payouts / finish order (format in `handicapper/results.py`).
  Results and payoffs are public data and may be committed; PPs are not.
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
  (otherwise it is "passed at the window": no cost, not a bet), the recommended Pick 3 / Pick 4 tickets are
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
