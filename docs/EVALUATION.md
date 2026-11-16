# Prospective evaluation: 217 races on 23 cards (2026-11-07 to 2026-11-15)

Unit: races. Probability floor in the log loss: 0.001. pre-race predictions only; chronological splits; nothing fitted on the races it is scored on.

Order of the breakdowns: surface and distance first (the splits that mattered in the frozen week), then field size, circuit and track (the owner's circuits pool tracks that share a horse population; track rows are shown for reference and are small).

| Vector | Races | Log loss | 95% CI | Brier | Top-prob hit rate | 95% CI | Uniform log loss | Mean gap to final odds |
|---|---|---|---|---|---|---|---|---|
| public market baseline (morning line renormalised) | 139 | 1.797 | [1.7044, 1.8955] | 0.8025 | 0.273 (38) | [0.2061, 0.3528] | 1.9736 | 0.0413 |
| rule heuristic (softmax of the ability score) | 217 | 1.9659 | [1.8164, 2.1238] | 0.8494 | 0.304 (66) | [0.2468, 0.3683] | 2.0164 | 0.0701 |
| engine blend as printed (win_prob) | 217 | 1.873 | [1.7531, 2.0138] | 0.8104 | 0.323 (70) | [0.2639, 0.3874] | 2.0164 | 0.0518 |
| final-odds market (hindsight: not available before the race) | 217 | 1.696 | [1.5962, 1.7999] | 0.766 | 0.359 (78) | [0.2986, 0.4252] | 2.0164 | 0.0 |

## Reliability (every horse's predicted win probability, binned)

**market**

| Bin | Horses | Mean predicted | Observed | Wins |
|---|---|---|---|---|
| 0.00-0.05 | 143 | 0.0379 | 0.035 | 5 |
| 0.05-0.10 | 300 | 0.0748 | 0.07 | 21 |
| 0.10-0.15 | 238 | 0.124 | 0.1218 | 29 |
| 0.15-0.20 | 164 | 0.1759 | 0.1768 | 29 |
| 0.20-0.30 | 136 | 0.241 | 0.2574 | 35 |
| 0.30-0.40 | 45 | 0.3366 | 0.3333 | 15 |
| 0.40-0.60 | 9 | 0.4587 | 0.4444 | 4 |
| 0.60-1.00 | 1 | 0.7612 | 1.0 | 1 |

**model**

| Bin | Horses | Mean predicted | Observed | Wins |
|---|---|---|---|---|
| 0.00-0.05 | 635 | 0.0259 | 0.0472 | 30 |
| 0.05-0.10 | 412 | 0.0705 | 0.1311 | 54 |
| 0.10-0.15 | 190 | 0.1242 | 0.1526 | 29 |
| 0.15-0.20 | 131 | 0.1729 | 0.1298 | 17 |
| 0.20-0.30 | 137 | 0.2435 | 0.1825 | 25 |
| 0.30-0.40 | 62 | 0.3439 | 0.2903 | 18 |
| 0.40-0.60 | 78 | 0.5013 | 0.3205 | 25 |
| 0.60-1.00 | 42 | 0.7494 | 0.4524 | 19 |

**blend**

| Bin | Horses | Mean predicted | Observed | Wins |
|---|---|---|---|---|
| 0.00-0.05 | 450 | 0.0266 | 0.0311 | 14 |
| 0.05-0.10 | 502 | 0.0731 | 0.1076 | 54 |
| 0.10-0.15 | 248 | 0.1235 | 0.1371 | 34 |
| 0.15-0.20 | 171 | 0.1719 | 0.152 | 26 |
| 0.20-0.30 | 153 | 0.2384 | 0.2026 | 31 |
| 0.30-0.40 | 69 | 0.3357 | 0.2899 | 20 |
| 0.40-0.60 | 74 | 0.4702 | 0.3649 | 27 |
| 0.60-1.00 | 20 | 0.6925 | 0.55 | 11 |

## By surface (log loss; races)

| surface | races | market | model | blend |
|---|---|---|---|---|
| dirt | 124 | 1.6857 | 1.9424 | 1.8354 |
| turf | 60 | 1.9696 | 2.0821 | 1.9965 |
| aw | 33 | 1.8274 | 1.8426 | 1.7899 |

## By distance (log loss; races)

| distance | races | market | model | blend |
|---|---|---|---|---|
| route (8f+) | 100 | 1.8493 | 1.9798 | 1.8843 |
| sprint (<8f) | 117 | 1.7408 | 1.9539 | 1.8633 |

## By field size (log loss; races)

| field size | races | market | model | blend |
|---|---|---|---|---|
| 6-7 | 88 | 1.7751 | 2.0909 | 1.9425 |
| 8-9 | 61 | 1.7868 | 1.983 | 1.8661 |
| 10+ | 43 | 2.3202 | 2.1325 | 2.1296 |
| <=5 | 25 | 1.3238 | 1.1974 | 1.2041 |

## By circuit (log loss; races)

| circuit | races | market | model | blend |
|---|---|---|---|---|
| Kentucky | 72 | 1.9252 | 1.8914 | 1.8698 |
| NYRA | 50 | 1.6361 | 1.9811 | 1.8759 |
| SoCal | 43 | 1.7932 | 1.9957 | 1.8162 |
| Florida | 52 | 1.7864 | 2.0296 | 1.9216 |

## By track (log loss; races)

| track | races | market | model | blend |
|---|---|---|---|---|
| CD | 72 | 1.9252 | 1.8914 | 1.8698 |
| BEL | 50 | 1.6361 | 1.9811 | 1.8759 |
| DMR | 43 | 1.7932 | 1.9957 | 1.8162 |
| GP | 52 | 1.7864 | 2.0296 | 1.9216 |

## By condition (log loss; races)

| condition | races | market | model | blend |
|---|---|---|---|---|
| fast | 142 | 1.7276 | 1.8401 | 1.7627 |
| firm | 25 | 2.253 | 2.4564 | 2.353 |
| good | 27 | 1.5613 | 1.9459 | 1.8156 |
| muddy | 16 | 1.856 | 2.2225 | 2.1552 |
| sloppy | 7 | 1.5939 | 2.2552 | 1.9734 |

## By pace shape (log loss; races)

| pace shape | races | market | model | blend |
|---|---|---|---|---|
| hot | 79 | 1.8763 | 2.1289 | 2.0044 |
| soft | 49 | 1.6988 | 1.8029 | 1.7377 |
| honest | 58 | 1.7343 | 1.7064 | 1.6369 |
| lone | 31 | 1.8695 | 2.2934 | 2.1938 |

## By clock (log loss; races)

| clock | races | market | model | blend |
|---|---|---|---|---|
| after-cutoff | 213 | 1.7995 | 1.9799 | 1.8839 |
| before-cutoff | 4 | 1.6284 | 1.22 | 1.2954 |

## Candidate blends (morning-line weight), chronological split

139 races; chosen on the first 69 (before 2026-11-12), reported on the last 70. research diagnostic: a weight chosen on the early half and reported on the late half; the configuration is not changed.

| ML weight | early log loss | late log loss |
|---|---|---|
| 0.0 | 2.0351 | 1.8702 |
| 0.2 | 1.9541 | 1.8012 |
| 0.35 | 1.9108 | 1.7725 |
| 0.5 | 1.8777 | 1.7558 |
| 0.65 | 1.8527 | 1.7491 |
| 0.8 | 1.8348 | 1.7521 |
| 1.0 | 1.8215 | 1.7728 |

Weight chosen on the early half: 1.0 -> late-half log loss 1.7728. The configuration keeps its own value.

# Data watch (as of 2026-11-16T16:06:36Z)

Races with a pre-race prediction and a chart result: **217** (4 made before the race's cutoff, 213 after; the owner's rule: a late run is a pre-race prediction all the same).

Per track: BEL 50, CD 72, DMR 43, GP 52.

| Gate | Capability | Needs | Have | Short by | Status |
|---|---|---|---|---|---|
| global_calibration | calibration pass of the softmax scale and the morning-line blend (global) | 300 races with a pre-race prediction and a chart result | 217 | 83 | `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA` |
| track_specific | anything circuit- or track-specific (weights, scale, blend) as shrunken effects under the global model | 400 races on one circuit (rules_config.json -> circuits) with a pre-race prediction and a result | 72 | 328 | `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA` |
| odds_drift | late-odds drift forecast | 150 races with a complete tote history (final board with history stored) | 0 | 150 | `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA` |
| timeform_value | Timeform's incremental value | 200 races with both Brisnet and Timeform figures and a result | 0 | 200 | `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA` |

Circuit gate: Kentucky 72 (CD 72), Florida 52 (GP 52), NYRA 50 (BEL 50), SoCal 43 (DMR 43).

Basis: pooling assumption chosen by the owner: tracks of one circuit (rules_config.json -> circuits) are counted together; this is a judgement about shared horse populations, not a statistical result. Surface and distance splits come first in the evaluation because the frozen week showed the turf / dirt gap is larger than any track difference.

Thresholds are proposals the owner can change in `rules_config.json` -> `data_watch.gates`; the code only counts. Until a gate is met its capability stays `DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA`; when it is met the status becomes `GATE_MET_AWAITING_OWNER_REVIEW` and nothing is fitted until the owner says so.
