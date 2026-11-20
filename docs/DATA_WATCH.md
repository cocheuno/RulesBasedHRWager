# Data watch (as of 2026-11-20T12:29:45Z)

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
