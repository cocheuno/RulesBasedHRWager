# Frozen-week review — 2026-11-07 to 2026-11-15

Engine frozen at the configuration of c8267c9 (PRs 29 to 38) for the whole period; the data-integrity PRs 40 to 47
changed no score, pick or ticket. 23 cards with pre-race snapshots and chart results, 219 races. The two 11/06
cards predate snapshots and are excluded.

## The week in one table

| | |
|---|---|
| Top pick won | 66 of 219 (30%) |
| Winner in engine's top three | 133 of 219 (61%) |
| Post-time favourite won | 79 of 219 (36%); the top pick was the favourite in 118 races |
| Brisnet pick won | 55 of 219 (25%) |
| Winner had been eliminated | 4 of 219 |
| Counted bets | 979; 177 hit |
| Staked / returned | $3,855.00 / $2,627.26, −32% |
| Passed on price / not offered | 49 / 3 |
| Pick 3 and 4, tracked only | 8 of 176 tickets, $1,049.50 → $336.27, −68% |

By day: 11/07 −52%, 11/08 −20%, 11/11 +38%, 11/12 −17%, 11/13 −49%, 11/14 −44%, 11/15 −23%.

By bet type: win 28 of 141 (−20%), exacta 60 of 241 (−21%), double 36 of 197 (−23%), trifecta 50 of 339 (−41%),
superfecta 3 of 61 (−52%).

Trifecta by structure: key first 27 of 156 (−26%), key second 11 of 119 (−22%), four-horse box 12 of 64
($714 → $215, −70%).

By confidence: high 35% top picks and −17% on bets; medium 20% and −52%; low 2 races.

By surface: dirt 35% top picks (−19% on bets), all-weather 39% (−46%), turf 16% (−48%). Firm turf: 1 top pick in
25 races; exactas −81%, trifectas −90%, win bets +11%.

By condition: fast 36%; good 30%; muddy and sloppy 5 of 23 (22%).

By pace shape: honest 39% top picks (−18%), soft 37% (−29%), hot 22% (−36%), lone speed 23% (−51%). In the 80
hot-pace races early runners won 43 and closers 30. In the 31 lone-speed races the speed held 9 times and a
closer won 14.

Top-pick calibration: 20–30% bucket won 19%; 30–40% won 28%; 40–50% won 37%; 50%+ won 41%. Over-confident
only above 50%.

Best-bets rule (top two races per card by win probability, win price met): 12 of 45, $2 win −13%.

## What re-scoring the frozen snapshots says

Every snapshot carries each horse's rule contributions, so candidate scoring changes can be tried without
betting them. Re-ranking all 219 races:

| Change | Top pick wins | Winner in top 3 |
|---|---|---|
| As run | 66 | 133 |
| Speed family capped at 20 / 15 / 12 / 10 points | 67 / 65 / 68 / 65 | 133 / 133 / 134 / 136 |
| Drop P1 (lone speed) | 67 | 133 |
| Drop P2 (pace penalty and closer bonus) | 66 | 132 |
| Drop both | 67 | 132 |
| Drop S7 (Prime Power) | 69 | 132 |
| Drop S3 (par comparison) | 68 | 130 |

None of the scoring changes proposed during the week moves the needle. The top pick barely changes under any
of them. The losses are in which races and which structures get bet, not in the weights.

## What bet-selection changes would have done

| Policy, applied to the week as bet | Bets | Staked → returned |
|---|---|---|
| As bet | 971 | $3,855 → $2,627 (−32%) |
| Without the four-horse box | 907 | $3,141 → $2,412 (−23%) |
| No trifecta or superfecta outside high confidence | 889 | $3,069 → $2,412 (−21%) |
| No bets at all on turf | 691 | $2,705 → $2,029 (−25%) |

## Recommendations for the decisions table

| Finding | Recommendation | Why |
|---|---|---|
| Four-horse trifecta box | **Drop** | 12 of 64, −70%; the single largest loss and it removes a quarter of the deficit |
| Lone-speed call (P1) | **Keep the weight; stop betting the shape** | Dropping P1 changes one race; bets in lone-speed races lost 51% because the shape itself is wrong 22 times in 31 |
| Turf | **Change: win bets only on turf; no exactas, trifectas, superfectas or doubles on firm turf** | Top pick 1 of 25 on firm; firm exotics −81 to −90%; firm win bets +11% |
| Off track | **Keep; add the track-condition and off-turf inputs from the Equibase page** | 23 races is too few; Belmont 11/15 ran three "turf" races on dirt and the engine scored them as turf |
| Speed-rule stacking cap | **Keep as is** | No cap helps on 219 races |
| Hot-pace trigger | **Keep the weights; watch** | Early types won 43 of 80 "hot" races; dropping P2 does not change the picks, so the fix is the trigger, which needs features the snapshots do not carry; test after the next 200 races |
| Pools not offered (Equibase page) | **Change: suppress the suggestion** | Data already captured; three not-offered rows this week |
| Best bets of the day | **Add as a view, labelled** | 12 of 45, −13% over the week; useful as a front page, not an edge |
| Pick 3 and Pick 4 | **Keep building, keep tracked** | 8 of 176, −68%; cheap to show, not a bet |
| Doubles | **Keep; the turf rule removes the losing half** | Dirt −15%, all-weather +20%, turf −57% |
| Medium-confidence races | **Change: exacta box only** | Medium trifectas −72%, win bets −36%; medium exactas −38% but the exacta box is the cheapest way to stay in the race |

Applying the first, third and last together on the week as bet: 889 bets, $3,069 → $2,412, −21%, with turf
exotics removed on top of that about −17%. Still a losing week. The honest reading: the engine finds the winner
in its top three in three races of five and is calibrated below 50%; it does not find enough winners at prices
that pay, and the structures around its picks were costing more than the picks themselves.

## Timeform

Two days of TimeformUS PPs, 79 races. Timeform's top-figure horse won 15; the engine's top pick won 25; the
favourite 30. Where the two disagreed, the engine won 13 and Timeform 5. Timeform's early-pace figures called
15 lone-speed races on 11/14 and the lone horse won one. No evidence that the figures improve selection or
the pace call. Recommendation: keep the reader, stop buying daily, buy a card occasionally as a second look.

## Data and routine items (no scoring change; can go in before the freeze ends)

- The chart reader's surface field reads "DIRT" for every race, turf and all-weather included. Fix, and use
  the Equibase page's "Off Turf" line to switch a race's surface before scoring.
- The Equibase changes page was never dropped on a card this week; the scratch lists were typed and matched
  the pages exactly every day. The page's condition and off-turf lines are the reason to drop it anyway.
- Scratches were entered after the races on 11/12 and 11/13 and during the cards on 11/14 and 11/15. The
  per-race cutoff (Carovex Phase A) is the structural fix; until then, run with scratches before first post.
- Gulfstream 11/15 R7 double: payout not on file; a chart pool line the reader missed. Fixture wanted.
- Snapshots: 10 to 13 runs per card on scratch-ticking days. Harmless, but a run that changes nothing should
  not write a new snapshot.

## Sample size

219 races with pre-race snapshots and results; 79 with a Timeform comparison; 0 with tote observations. Against
the Carovex Phase E gates (300 for a global calibration pass, 400 per track, 150 with tote histories, 200 with
both figure sets): the first gate is about two weeks away at the current rate, the per-track gates six to eight
weeks, the tote gate starts counting when Phase C runs.
