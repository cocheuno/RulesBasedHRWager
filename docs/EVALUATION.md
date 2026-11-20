# Prospective evaluation: 243 races on 26 cards (2026-11-07 to 2026-11-19)

Unit: races. Probability floor in the log loss: 0.001. pre-race predictions only; chronological splits; nothing fitted on the races it is scored on.

Order of the breakdowns: surface and distance first (the splits that mattered in the frozen week), then field size, circuit and track (the owner's circuits pool tracks that share a horse population; track rows are shown for reference and are small).

| Vector | Races | Log loss | 95% CI | Brier | Top-prob hit rate | 95% CI | Uniform log loss | Mean gap to final odds |
|---|---|---|---|---|---|---|---|---|
| public market baseline (morning line renormalised) | 155 | 1.8158 | [1.7251, 1.8993] | 0.8057 | 0.265 (41) | [0.2014, 0.339] | 1.9816 | 0.0427 |
| rule heuristic (softmax of the ability score) | 243 | 1.9929 | [1.8456, 2.1432] | 0.8527 | 0.304 (74) | [0.2501, 0.3651] | 2.0217 | 0.0702 |
| engine blend as printed (win_prob) | 243 | 1.9083 | [1.7846, 2.0416] | 0.8136 | 0.321 (78) | [0.2655, 0.3821] | 2.0217 | 0.0519 |
| final-odds market (hindsight: not available before the race) | 243 | 1.7027 | [1.6157, 1.7947] | 0.7647 | 0.358 (87) | [0.3004, 0.4201] | 2.0217 | 0.0 |

## Reliability (every horse's predicted win probability, binned)

**market**

| Bin | Horses | Mean predicted | Observed | Wins |
|---|---|---|---|---|
| 0.00-0.05 | 165 | 0.0378 | 0.0424 | 7 |
| 0.05-0.10 | 341 | 0.075 | 0.0733 | 25 |
| 0.10-0.15 | 263 | 0.1243 | 0.1141 | 30 |
| 0.15-0.20 | 187 | 0.1759 | 0.1872 | 35 |
| 0.20-0.30 | 147 | 0.2411 | 0.2381 | 35 |
| 0.30-0.40 | 50 | 0.3358 | 0.34 | 17 |
| 0.40-0.60 | 10 | 0.4624 | 0.5 | 5 |
| 0.60-1.00 | 1 | 0.7612 | 1.0 | 1 |

**model**

| Bin | Horses | Mean predicted | Observed | Wins |
|---|---|---|---|---|
| 0.00-0.05 | 722 | 0.0259 | 0.0485 | 35 |
| 0.05-0.10 | 467 | 0.0705 | 0.1285 | 60 |
| 0.10-0.15 | 210 | 0.1241 | 0.1429 | 30 |
| 0.15-0.20 | 140 | 0.1728 | 0.1357 | 19 |
| 0.20-0.30 | 151 | 0.2431 | 0.1987 | 30 |
| 0.30-0.40 | 71 | 0.3421 | 0.2817 | 20 |
| 0.40-0.60 | 91 | 0.5014 | 0.3077 | 28 |
| 0.60-1.00 | 46 | 0.7511 | 0.4565 | 21 |

**blend**

| Bin | Horses | Mean predicted | Observed | Wins |
|---|---|---|---|---|
| 0.00-0.05 | 514 | 0.0269 | 0.035 | 18 |
| 0.05-0.10 | 565 | 0.073 | 0.1062 | 60 |
| 0.10-0.15 | 278 | 0.1233 | 0.1295 | 36 |
| 0.15-0.20 | 187 | 0.1718 | 0.1497 | 28 |
| 0.20-0.30 | 171 | 0.2398 | 0.2105 | 36 |
| 0.30-0.40 | 76 | 0.3359 | 0.3026 | 23 |
| 0.40-0.60 | 85 | 0.4678 | 0.3529 | 30 |
| 0.60-1.00 | 22 | 0.6921 | 0.5455 | 12 |

## By surface (log loss; races)

| surface | races | market | model | blend |
|---|---|---|---|---|
| dirt | 140 | 1.701 | 1.9487 | 1.8516 |
| turf | 69 | 1.982 | 2.1375 | 2.0626 |
| aw | 34 | 1.8939 | 1.8815 | 1.8289 |

## By distance (log loss; races)

| distance | races | market | model | blend |
|---|---|---|---|---|
| route (8f+) | 113 | 1.871 | 2.0427 | 1.9631 |
| sprint (<8f) | 130 | 1.7585 | 1.9496 | 1.8607 |

## By field size (log loss; races)

| field size | races | market | model | blend |
|---|---|---|---|---|
| 6-7 | 96 | 1.7462 | 2.0784 | 1.944 |
| 8-9 | 70 | 1.8514 | 2.0868 | 1.9699 |
| 10+ | 50 | 2.3527 | 2.1301 | 2.1363 |
| <=5 | 27 | 1.3295 | 1.1913 | 1.1995 |

## By circuit (log loss; races)

| circuit | races | market | model | blend |
|---|---|---|---|---|
| Kentucky | 90 | 1.9461 | 1.9833 | 1.966 |
| NYRA | 58 | 1.6772 | 1.9727 | 1.8751 |
| SoCal | 43 | 1.7932 | 1.9957 | 1.8162 |
| Florida | 52 | 1.7864 | 2.0296 | 1.9216 |

## By track (log loss; races)

| track | races | market | model | blend |
|---|---|---|---|---|
| CD | 90 | 1.9461 | 1.9833 | 1.966 |
| BEL | 58 | 1.6772 | 1.9727 | 1.8751 |
| DMR | 43 | 1.7932 | 1.9957 | 1.8162 |
| GP | 52 | 1.7864 | 2.0296 | 1.9216 |

## By condition (log loss; races)

| condition | races | market | model | blend |
|---|---|---|---|---|
| fast | 159 | 1.7504 | 1.8642 | 1.7928 |
| firm | 34 | 2.224 | 2.4697 | 2.3927 |
| good | 27 | 1.5613 | 1.9459 | 1.8156 |
| muddy | 16 | 1.856 | 2.2225 | 2.1552 |
| sloppy | 7 | 1.5939 | 2.2552 | 1.9734 |

## By pace shape (log loss; races)

| pace shape | races | market | model | blend |
|---|---|---|---|---|
| hot | 84 | 1.9044 | 2.1279 | 2.0129 |
| honest | 67 | 1.7683 | 1.8127 | 1.7498 |
| soft | 54 | 1.6936 | 1.7675 | 1.7044 |
| lone | 38 | 1.89 | 2.3322 | 2.2464 |

## By clock (log loss; races)

| clock | races | market | model | blend |
|---|---|---|---|---|
| after-cutoff | 230 | 1.8094 | 2.0195 | 1.9273 |
| before-cutoff | 13 | 1.9208 | 1.5213 | 1.573 |

## Candidate blends (morning-line weight), chronological split

155 races; chosen on the first 77 (before 2026-11-13), reported on the last 78. research diagnostic: a weight chosen on the early half and reported on the late half; the configuration is not changed.

| ML weight | early log loss | late log loss |
|---|---|---|
| 0.0 | 2.0346 | 1.8469 |
| 0.2 | 1.9564 | 1.7925 |
| 0.35 | 1.9146 | 1.7722 |
| 0.5 | 1.8826 | 1.763 |
| 0.65 | 1.8584 | 1.7633 |
| 0.8 | 1.8413 | 1.773 |
| 1.0 | 1.8287 | 1.8032 |

Weight chosen on the early half: 1.0 -> late-half log loss 1.8032. The configuration keeps its own value.

# Data watch (as of 2026-11-20T12:29:43Z)

Races with a pre-race prediction and a chart result: **243** (13 made before the race's cutoff, 230 after; the owner's rule: a late run is a pre-race prediction all the same).

Per track: BEL 58, CD 90, DMR 43, GP 52.

| Gate | Capability | Needs | Have | Short by | Status |
|---|---|---|---|---|---|
| global_calibration | calibration pass of the softmax scale and the morning-line blend (global) | 300 races with a pre-race prediction and a chart result | 243 | 57 | `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA` |
| track_specific | anything circuit- or track-specific (weights, scale, blend) as shrunken effects under the global model | 400 races on one circuit (rules_config.json -> circuits) with a pre-race prediction and a result | 90 | 310 | `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA` |
| odds_drift | late-odds drift forecast | 150 races with a complete tote history (final board with history stored) | 7 | 143 | `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA` |
| timeform_value | Timeform's incremental value | 200 races with both Brisnet and Timeform figures and a result | 9 | 191 | `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA` |

Circuit gate: Kentucky 90 (CD 90), NYRA 58 (BEL 58), Florida 52 (GP 52), SoCal 43 (DMR 43).

Basis: pooling assumption chosen by the owner: tracks of one circuit (rules_config.json -> circuits) are counted together; this is a judgement about shared horse populations, not a statistical result. Surface and distance splits come first in the evaluation because the frozen week showed the turf / dirt gap is larger than any track difference.

Thresholds are proposals the owner can change in `rules_config.json` -> `data_watch.gates`; the code only counts. Until a gate is met its capability stays `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA`; when it is met the status becomes `GATE_MET_AWAITING_OWNER_REVIEW` and nothing is fitted until the owner says so.
