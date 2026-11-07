# Handicapping rule catalog

Points = factor × weight. Weights are defaults; override in rules_config.json.

## Speed

| Id | Rule | Weight | Definition |
|---|---|---|---|
| S1 | Top last-race speed figure | 6 | Highest Brisnet speed figure in the field last time out: full credit; within 2 points of the top: half. |
| S2 | Best of last three speed figures | 6 | Best Brisnet speed figure among the last three starts ranks 1st (1.0), 2nd (0.6) or 3rd (0.3) in the field. |
| S3 | Average speed vs. class par | 5 | Average of the last three speed figures compared with the Brisnet PAR for today's class: >= par +3: 1.0; >= par: 0.5; par-4 .. par-1: 0; below par-4: -0.6; below par-8: -1.0. |
| S4 | Best figure on today's surface & distance category | 5 | Best speed figure earned in races matching today's surface and sprint/route category ranks 1st (1.0) or 2nd (0.5). A horse with no matching race gets no credit here (handled by D-rules). |
| S5 | Improving / declining figure pattern | 3 | Three consecutively rising speed figures: +1.0 (horse is on an upward form cycle). Three consecutively falling figures: -1.0 (tailing off). |
| S6 | Bounce risk after a career-top figure | 3 | Last race was a new career top by 5+ points over every previous figure AND the horse has 3+ starts: -1.0 (regression to the mean is likely, especially off a short rest). |
| S7 | Prime Power rank | 7 | Brisnet Prime Power rank in the field: 1st 1.0, 2nd 0.6, 3rd 0.35. Bonus +0.4 if the top-ranked horse is 4+ points clear of the second. |
| S8 | Consistently near par | 3 | All of the last three speed figures are within 3 points of today's par or better: 1.0 (reliable, no bounce risk). |

## Distance

| Id | Rule | Weight | Definition |
|---|---|---|---|
| D7 | Best figure at the exact distance | 2 | Brisnet 'best speed at distance' (Dis record) ranks 1st in the field: 1.0; 2nd: 0.5. |
| D1 | Record at today's distance | 3 | Starts at today's distance: a win: 1.0; ITM (no win) in 2+ tries: 0.5; 0-for-4+ with no ITM: -0.6. |
| D2 | Record on today's surface | 3 | Starts on today's surface (dirt-fast or turf): win% >= 25 with 3+ starts: 1.0; ITM% >= 50: 0.5; 0 for 6+ with ITM% < 20: -0.7. |
| D3 | Surface switch with no experience | 3 | Horse has never run on today's surface: judged by Brisnet pedigree rating for that surface (>= 110: +0.5; 100-109: 0; < 100: -0.7) and, turf-to-dirt, by the trainer's 'Turf to Dirt' stat (win% >= 20: +0.5). |
| D4 | Distance change suitability | 2.5 | Stretching out sprint-to-route: +0.6 if late pace (LP) avg >= par-late and sire AWD >= 7.0; -0.6 if the horse has faded (negative last-race 2c pace figure change) and sire AWD < 6.5. Route-to-sprint: +0.5 if best E2 is within 3 of the field's best; -0.5 otherwise. |
| D5 | Track record (today's track) | 1.5 | Won at today's track: 1.0; ITM 2+ times here: 0.5. |
| D6 | Turf pedigree / proven turf speed (turf races only) | 2 | Turf race: best turf figure ranks 1st: +1.0; horse with 0 turf starts and pedigree turf rating < 100: -0.8. |

## Class

| Id | Rule | Weight | Definition |
|---|---|---|---|
| C1 | Class drop | 5 | Today's class level is below the last race's (by the class ladder): drop of 1-3 levels 0.6, 3+ levels 1.0. If the horse was beaten 10+ lengths last time the drop is discounted to 0.3 ("dropping for a reason"). |
| C2 | Class rise | 4 | Today's class level is above the last race's: -0.6 for a 1-3 level rise, -1.0 for 3+. Waived (0) if the horse won last time by 2+ lengths or earned a figure above par. |
| C3 | Class rating rank | 4 | Average Brisnet class rating of the last three starts ranks 1st (1.0), 2nd (0.5) or 3rd (0.25). |
| C4 | Proven at today's level | 3 | Competitive (finished within 3 lengths) in a race whose class level was >= today's within the last 3 starts: 1.0. |
| C5 | Last race rating beats the field | 3 | Brisnet race rating of the last race (strength of the field it faced) ranks 1st: 1.0, 2nd: 0.5. |
| C6 | Claimed / protected drop | 2 | Horse is dropping in class off a claim (new barn moving it down) with a trainer winning >= 15%: 1.0. |

## Pace

| Id | Rule | Weight | Definition |
|---|---|---|---|
| P1 | Lone early speed | 7 | Only one horse in the field has early-speed points >= 5 and is at least 2 points clear of all others, with no other 'E' type: that horse gets 1.0 (uncontested lead). Full credit on dirt, 0.7 on turf. |
| P2 | Speed duel penalty / closer bonus | 4 | Hot pace shape (3+ 'E' types or 3+ horses with 6+ speed points): E types -1.0, E/P -0.5, P +0.5, S +1.0. Soft pace shape (<= 2 early types, no lone speed): E/E-P +0.4, S -0.4. |
| P3 | Best early pace figure (E1/E2) | 4 | Best E2 pace figure in the field: 1.0 in sprints, 0.6 in routes; best E1 adds 0.4 (sprints only). |
| P4 | Best late pace figure | 4 | Best late-pace (LP) figure in the field: 1.0 in routes/turf, 0.6 in dirt sprints; 2nd best 0.4. |
| P5 | Running style vs. track bias | 4 | Brisnet track-bias impact value for the horse's run style at today's surface/distance (meet totals): >= 1.30: 1.0; 1.10-1.29: 0.5; <= 0.60: -1.0; 0.61-0.85: -0.5. Weekly figures (if 5+ races) add half credit. |
| P6 | Post position vs. bias | 2 | Track-bias impact value for the post-position group (RAIL, 1-3, 4-7, 8+): >= 1.3: 1.0; <= 0.7: -1.0 (meet totals). Rail horse with E/P or P style in a route adds nothing extra. |
| P7 | Early speed points rank | 2 | Brisnet early-speed points: 7-8 points 1.0, 5-6 points 0.5 (only when the pace shape is not hot). |
| P8 | Pace figures vs. par | 2.5 | Early types: average E2 of last 3 >= par E2 + 2 in a soft/lone pace: +1.0 (can control the race). Closers: average late pace >= par late + 3 in a hot pace: +1.0 (will be running at the end). Early type whose average E2 is 6+ below par: -0.6 (will not be able to get position). |

## Form

| Id | Rule | Weight | Definition |
|---|---|---|---|
| F1 | Won last race | 3 | Won last start: 1.0; won 'handily/drew off/driving' (strong win comment): 1.4. |
| F2 | In the money last race | 2 | Finished 2nd or 3rd last time beaten <= 3 lengths: 1.0; 4th-5th beaten <= 3 lengths: 0.5. |
| F3 | Troubled trip last out | 3 | Last-race comment shows trouble (bumped, steadied, checked, blocked, wide trip, slow start, etc.) and the horse still finished within 6 lengths: 1.0 (excuse); trouble and beaten > 6: 0.4. |
| F4 | Closed ground late last out | 2 | Gained 2+ lengths from the second call to the finish last time, or passed horses in the stretch: 1.0. |
| F5 | Bad effort last out | 3 | Last race comment is negative (faded, tired, no factor, eased, stopped...) and beaten 8+ lengths with no trouble: -1.0. Beaten 15+: -1.5. |
| F6 | Layoff handling | 3 | Days since last race: 46-90 days with a flagged/positive layoff trainer stat (win% >= 15): +0.5; 91-180 days: -0.3 unless 3+ works incl. a 5f+ work (then 0); 181+ days: -1.0 unless trainer layoff stat >= 18% and 4+ works (then -0.3). <= 14 days ('quick back'): +0.3 if last race was good. |
| F7 | Second / third start off the layoff | 2 | Second start after a 60+ day layoff: +1.0 (classic improvement spot) if the comeback race was within 6 lengths; third start: +0.5. |
| F8 | Consistency | 3 | Career ITM% >= 60 with 4+ starts: 1.0; >= 45: 0.5; <= 20% with 8+ starts: -0.7. |
| F9 | Recent workout pattern | 2 | A bullet work (fastest of the day) among the last 4 works: +0.7; two or more top-15% works: +0.5; no workout since a layoff of 45+ days: -0.5. |
| F10 | Two straight in-the-money finishes | 1.5 | ITM in each of the last two starts: 1.0; last three: 1.5. |

## Connections

| Id | Rule | Weight | Definition |
|---|---|---|---|
| K1 | Trainer win percentage (year) | 3 | Trainer's current-year win%: >= 22: 1.0; 17-21: 0.6; 12-16: 0.2; <= 7 (with 30+ starts): -0.8. |
| K2 | Trainer angle stats | 3 | Brisnet trainer category stats that apply today (e.g. '2nd off layoff', 'Turf to Dirt', '1stTimeBlinkers'): any category with 15+ starts and win% >= 20 or ROI >= +0.20: +0.6 each (max 1.2); any with 15+ starts and win% <= 7: -0.5 each (max -1.0). A '+' flag from Brisnet adds 0.2. |
| K3 | Jockey win percentage | 2 | Jockey current-year win%: >= 18: 1.0; 13-17: 0.5; <= 6 with 50+ mounts: -0.7. |
| K4 | Jockey/trainer combination | 2 | Jockey-with-this-trainer (last 60 days) stat: 5+ starts and win% >= 25: 1.0; 5+ starts and 0%: -0.5. |
| K5 | Hot trainer | 2 | Brisnet 'Hot Trainer in last 14 days' comment present: 1.0. |
| K7 | Trainer meet form | 1.5 | Trainer's record at the current meet: 8+ starts and win% >= 25: +1.0; 15+ starts and 0 wins: -0.6. |
| K6 | Rider upgrade | 1.5 | Jockey change to a rider winning >= 15% on the year, after a rider who was not listed: 1.0. |

## Age_Weight

| Id | Rule | Weight | Definition |
|---|---|---|---|
| A1 | Weight / age concession | 1 | Carries 4+ lbs less than the heaviest weight in the field: +0.5; 3yo against older after September (gets the scale-of-weights allowance and is still maturing): +0.3. |

## Equipment

| Id | Rule | Weight | Definition |
|---|---|---|---|
| E1 | First-time blinkers | 2 | Blinkers added today: trainer '1stTimeBlinkers' win% >= 15 (10+ starts): +1.0; <= 7: -0.6; otherwise +0.2. |
| E2 | Blinkers off | 1 | Blinkers removed today (often a horse that was too keen): +0.3 for P/S types, 0 otherwise. |
| E3 | First-time Lasix | 1 | First-time Lasix (typically a foreign import or a 2yo): +0.5. |

## Comments

| Id | Rule | Weight | Definition |
|---|---|---|---|
| Q1 | QuickPlay positive comments | 1.2 | Each Brisnet positive (ñ) comment: +0.5; strong ones (speed rating best in field, class drop, hot trainer...): +1.0. Max 3.0. |
| Q2 | QuickPlay negative comments | 1.2 | Each Brisnet negative (×) comment: -0.5; strong ones (poor figures, always far back, beaten by weaker, poor trainer...): -1.0. Min -3.0. The generic 'Has not raced for more than 2 months' counts only -0.25 (layoffs are handled by F6). |

## Maiden

| Id | Rule | Weight | Definition |
|---|---|---|---|
| M1 | First-time starter profile | 4 | Debut runner: trainer '1st time starter' stat win% >= 15 (+0.6), sire 1st-time-starter win% >= 14 (+0.4), bullet or top-10% work in last 4 (+0.4), 4+ published works (+0.2); debuting in a maiden-claiming race (-0.5); fewer than 3 works (-0.5). |
| M2 | Maiden-special-weight dropper into maiden claiming | 5 | Today is a maiden-claiming race and the horse's last 1-2 starts were in maiden special weight / higher-priced maiden claimers with a speed figure within 4 of today's par: +1.0 (the classic MSW-to-MCL drop). |
| M3 | Chronic maiden | 3 | Maiden with 8+ starts: -0.8; 12+ starts: -1.2. Maiden with 3+ seconds and no win ('sucker horse'): additional -0.4. |
| M4 | Lightly raced improver | 2 | Horse with 1-3 career starts whose last figure improved 5+ points on its previous start: +1.0; second career start after a debut within 4 lengths: +0.6. |

## Elimination

| Id | Rule | Weight | Definition |
|---|---|---|---|
| X1 | Hopelessly slow | 1 (hard) | Throw-out: best speed figure of the last three starts is 10+ points below today's par AND the horse has 3+ starts AND it is not dropping 3+ class levels. |
| X2 | Long layoff, no foundation | 1 (hard) | Throw-out: 365+ days since last race with fewer than 4 workouts. |
| X3 | Also-eligible / main-track-only | 1 (hard) | Flag (not a throw-out): horse is on the also-eligible list or main-track-only; it runs only if scratches occur. Scored normally but reported with an AE/MTO flag. |
| X4 | Badly outclassed | 1 (hard) | Throw-out: average class rating of the last three starts is 8+ points below the field's best AND the horse is not dropping in class. |

## Value

| Id | Rule | Weight | Definition |
|---|---|---|---|
| V1 | Morning-line value | 3 | Applied after scoring (see engine): compares the horse's score-implied win probability with the morning-line implied probability. Overlay (fair odds < ML by 30%+): +1.0; underlay (ML < 60% of fair): -0.8. Chalk at 6/5 or lower never gets a value bonus. |

