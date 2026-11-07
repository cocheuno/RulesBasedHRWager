# Brisnet Ultimate PPs → rules-based selections

Deterministic, auditable pipeline: **PDF → structured JSON → scored rule hits → 1–3 horses per race.**
No cloud services, no ML; every point on a horse's scoresheet is traceable to a named rule
with a one-line justification.

```
pip install pdfplumber              # the only dependency (poppler not required)

python pick.py dmr1106y.pdf                         # parse + score, print the report
python pick.py dmr1106y.pdf -o out/                 # also write <card>.card.json / .picks.json / .picks.md
python pick.py out/dmr1106y.card.json --race 4 --detail 2    # full rule-by-rule audit, one race
python pick.py --rules-doc > RULES.md               # regenerate the rule catalog
python -m brisnet_pp.parser dmr1106y.pdf -o card.json        # parser only
python validate_parse.py card.json                  # internal consistency checks on a parsed card
```

## Layout

```
brisnet_pp/
  symbols.py     decoding of Brisnet's PP2B symbol font (superscripts, fractions, race symbols)
  parser.py      coordinate-based PDF parser -> dict/JSON (races, horses, PP lines, workouts,
                 race summary table, track-bias stats, ranking boxes)
handicapper/
  features.py    per-horse derived features + field-relative ranks + pace scenario
  rules.py       the rule catalog (61 rules, each a pure function with its definition in the docstring)
  engine.py      scoring, value overlay, selection policy, markdown report
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
keeps the note.  Hard rules (`X*`) eliminate (negative factor) or flag (AE/MTO).  `V1`
compares the score-implied win probability (softmax over the field) with the morning line.

Categories: **S** speed · **C** class · **P** pace & bias · **F** form · **K** connections ·
**D** distance/surface · **E** equipment · **Q** QuickPlay comments · **M** maidens ·
**A** age/weight · **X** eliminations · **V** value.  See `RULES.md`.

Selection (`rules_config.json → selection`): the top horse is a **single** when it is
`single_gap` (7) points clear and the race is not contentious (fewer than 4 horses within
`spread_gap`); the 2nd is added when within `pair_gap` (4) or the race is contentious; a 3rd
when within `third_gap` (7).  Also-eligibles are never picked outright — they are reported
as "would be a play if it draws in".  ML ≤ 6/5 singles are keyed in exotics rather than bet to win.

### Tuning

* Change a weight: `"weights": {"S7": 5, "P5": 2}`; switch a rule off: `"disabled": ["V1"]`.
* Every run writes `*.picks.json`, which contains the full per-horse feature set and every
  rule hit — join it with results to back-test weights.
* Add a rule: write a function in `rules.py` with the `@rule` decorator and a docstring; it
  appears in the audit and in `RULES.md` automatically.

## Known limits

* Scratches and track condition are not in the PPs; re-run after scratches by editing the
  card JSON (delete the horse) or add a `--scratch` list (trivial to add in `pick.py`).
* Foreign (European / Meydan) lines carry no Brisnet figures; those horses are judged on
  class, comments and connections only (e.g. Tailgunner Joe, R6).
* The class ladder in `features.class_level` is calibrated for the Southern California
  circuit; adjust for other circuits.
* Weights are expert priors, not fitted; the audit trail exists precisely so they can be.
