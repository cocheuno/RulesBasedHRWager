# Prospective evaluation: 226 races on 24 cards (2026-11-07 to 2026-11-18)

Unit: races. Probability floor in the log loss: 0.001. pre-race predictions only; chronological splits; nothing fitted on the races it is scored on.

Order of the breakdowns: surface and distance first (the splits that mattered in the frozen week), then field size, circuit and track (the owner's circuits pool tracks that share a horse population; track rows are shown for reference and are small).

| Vector | Races | Log loss | 95% CI | Brier | Top-prob hit rate | 95% CI | Uniform log loss | Mean gap to final odds |
|---|---|---|---|---|---|---|---|---|
| public market baseline (morning line renormalised) | 146 | 1.8069 | [1.7127, 1.8931] | 0.8034 | 0.267 (39) | [0.202, 0.3442] | 1.9802 | 0.0417 |
| rule heuristic (softmax of the ability score) | 226 | 1.9535 | [1.8073, 2.094] | 0.8455 | 0.305 (69) | [0.2489, 0.3682] | 2.0174 | 0.0701 |
| engine blend as printed (win_prob) | 226 | 1.866 | [1.7417, 1.9949] | 0.8077 | 0.323 (73) | [0.2654, 0.3865] | 2.0174 | 0.0519 |
| final-odds market (hindsight: not available before the race) | 226 | 1.6905 | [1.6031, 1.7932] | 0.7632 | 0.363 (82) | [0.3029, 0.4273] | 2.0174 | 0.0 |

## Reliability (every horse's predicted win probability, binned)

**market**

| Bin | Horses | Mean predicted | Observed | Wins |
|---|---|---|---|---|
| 0.00-0.05 | 153 | 0.0377 | 0.0392 | 6 |
| 0.05-0.10 | 321 | 0.075 | 0.0717 | 23 |
| 0.10-0.15 | 250 | 0.1242 | 0.116 | 29 |
| 0.15-0.20 | 174 | 0.1758 | 0.1839 | 32 |
| 0.20-0.30 | 141 | 0.2411 | 0.2482 | 35 |
| 0.30-0.40 | 45 | 0.3366 | 0.3333 | 15 |
| 0.40-0.60 | 10 | 0.4624 | 0.5 | 5 |
| 0.60-1.00 | 1 | 0.7612 | 1.0 | 1 |

**model**

| Bin | Horses | Mean predicted | Observed | Wins |
|---|---|---|---|---|
| 0.00-0.05 | 659 | 0.0259 | 0.0455 | 30 |
| 0.05-0.10 | 428 | 0.0707 | 0.1308 | 56 |
| 0.10-0.15 | 202 | 0.1242 | 0.1485 | 30 |
| 0.15-0.20 | 133 | 0.1729 | 0.1278 | 17 |
| 0.20-0.30 | 147 | 0.2433 | 0.1973 | 29 |
| 0.30-0.40 | 66 | 0.3421 | 0.2879 | 19 |
| 0.40-0.60 | 80 | 0.4989 | 0.3125 | 25 |
| 0.60-1.00 | 43 | 0.7513 | 0.4651 | 20 |

**blend**

| Bin | Horses | Mean predicted | Observed | Wins |
|---|---|---|---|---|
| 0.00-0.05 | 463 | 0.0266 | 0.0302 | 14 |
| 0.05-0.10 | 526 | 0.0729 | 0.1065 | 56 |
| 0.10-0.15 | 262 | 0.1235 | 0.1336 | 35 |
| 0.15-0.20 | 177 | 0.172 | 0.1525 | 27 |
| 0.20-0.30 | 163 | 0.2395 | 0.2086 | 34 |
| 0.30-0.40 | 72 | 0.3351 | 0.2917 | 21 |
| 0.40-0.60 | 74 | 0.4702 | 0.3649 | 27 |
| 0.60-1.00 | 21 | 0.6935 | 0.5714 | 12 |

## By surface (log loss; races)

| surface | races | market | model | blend |
|---|---|---|---|---|
| dirt | 131 | 1.6964 | 1.9206 | 1.8207 |
| turf | 62 | 1.9863 | 2.0821 | 2.0022 |
| aw | 33 | 1.8274 | 1.8426 | 1.7899 |

## By distance (log loss; races)

| distance | races | market | model | blend |
|---|---|---|---|---|
| route (8f+) | 104 | 1.865 | 1.9776 | 1.8856 |
| sprint (<8f) | 122 | 1.7456 | 1.9329 | 1.8493 |

## By field size (log loss; races)

| field size | races | market | model | blend |
|---|---|---|---|---|
| 6-7 | 93 | 1.7579 | 2.0417 | 1.9029 |
| 8-9 | 62 | 1.8084 | 1.9955 | 1.8796 |
| 10+ | 46 | 2.3269 | 2.1294 | 2.1327 |
| <=5 | 25 | 1.3238 | 1.1974 | 1.2041 |

## By circuit (log loss; races)

| circuit | races | market | model | blend |
|---|---|---|---|---|
| Kentucky | 81 | 1.9354 | 1.8652 | 1.8505 |
| NYRA | 50 | 1.6361 | 1.9811 | 1.8759 |
| SoCal | 43 | 1.7932 | 1.9957 | 1.8162 |
| Florida | 52 | 1.7864 | 2.0296 | 1.9216 |

## By track (log loss; races)

| track | races | market | model | blend |
|---|---|---|---|---|
| CD | 81 | 1.9354 | 1.8652 | 1.8505 |
| BEL | 50 | 1.6361 | 1.9811 | 1.8759 |
| DMR | 43 | 1.7932 | 1.9957 | 1.8162 |
| GP | 52 | 1.7864 | 2.0296 | 1.9216 |

## By condition (log loss; races)

| condition | races | market | model | blend |
|---|---|---|---|---|
| fast | 149 | 1.7349 | 1.8257 | 1.7532 |
| firm | 27 | 2.2628 | 2.4286 | 2.3396 |
| good | 27 | 1.5613 | 1.9459 | 1.8156 |
| muddy | 16 | 1.856 | 2.2225 | 2.1552 |
| sloppy | 7 | 1.5939 | 2.2552 | 1.9734 |

## By pace shape (log loss; races)

| pace shape | races | market | model | blend |
|---|---|---|---|---|
| hot | 80 | 1.9 | 2.1368 | 2.0149 |
| soft | 51 | 1.6964 | 1.7899 | 1.7291 |
| honest | 61 | 1.7343 | 1.6898 | 1.6265 |
| lone | 34 | 1.8886 | 2.2407 | 2.1504 |

## By clock (log loss; races)

| clock | races | market | model | blend |
|---|---|---|---|---|
| after-cutoff | 213 | 1.7995 | 1.9799 | 1.8839 |
| before-cutoff | 13 | 1.9208 | 1.5213 | 1.573 |

## Candidate blends (morning-line weight), chronological split

146 races; chosen on the first 73 (before 2026-11-13), reported on the last 73. research diagnostic: a weight chosen on the early half and reported on the late half; the configuration is not changed.

| ML weight | early log loss | late log loss |
|---|---|---|
| 0.0 | 2.0384 | 1.8465 |
| 0.2 | 1.9613 | 1.785 |
| 0.35 | 1.9203 | 1.7609 |
| 0.5 | 1.8891 | 1.7483 |
| 0.65 | 1.8658 | 1.7453 |
| 0.8 | 1.8494 | 1.7514 |
| 1.0 | 1.8381 | 1.7758 |

Weight chosen on the early half: 1.0 -> late-half log loss 1.7758. The configuration keeps its own value.

# Data watch (as of 2026-11-18T22:54:47Z)

Races with a pre-race prediction and a chart result: **226** (13 made before the race's cutoff, 213 after; the owner's rule: a late run is a pre-race prediction all the same).

Per track: BEL 50, CD 81, DMR 43, GP 52.

| Gate | Capability | Needs | Have | Short by | Status |
|---|---|---|---|---|---|
| global_calibration | calibration pass of the softmax scale and the morning-line blend (global) | 300 races with a pre-race prediction and a chart result | 226 | 74 | `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA` |
| track_specific | anything circuit- or track-specific (weights, scale, blend) as shrunken effects under the global model | 400 races on one circuit (rules_config.json -> circuits) with a pre-race prediction and a result | 81 | 319 | `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA` |
| odds_drift | late-odds drift forecast | 150 races with a complete tote history (final board with history stored) | 7 | 143 | `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA` |
| timeform_value | Timeform's incremental value | 200 races with both Brisnet and Timeform figures and a result | 9 | 191 | `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA` |

Circuit gate: Kentucky 81 (CD 81), Florida 52 (GP 52), NYRA 50 (BEL 50), SoCal 43 (DMR 43).

Basis: pooling assumption chosen by the owner: tracks of one circuit (rules_config.json -> circuits) are counted together; this is a judgement about shared horse populations, not a statistical result. Surface and distance splits come first in the evaluation because the frozen week showed the turf / dirt gap is larger than any track difference.

Thresholds are proposals the owner can change in `rules_config.json` -> `data_watch.gates`; the code only counts. Until a gate is met its capability stays `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA`; when it is met the status becomes `GATE_MET_AWAITING_OWNER_REVIEW` and nothing is fitted until the owner says so.
