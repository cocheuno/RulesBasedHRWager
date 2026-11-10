# Race-day cheat sheet

Everything happens in Race Day Desk, the local app. PowerShell is used only to start it, stop it, and push the
results at the end of the day. All commands run from the `RulesBasedHRWager` folder.

`<card>` is the TwinSpires file code, e.g. `dmr1106y` (track + mmdd + y). The PP file, the results folder and the
results file all use it.

## 1. Once a day, before anything else

```powershell
git pull origin main
```

```powershell
python ui.py start
```

The browser opens http://127.0.0.1:8765 and the prompt comes back. If the app was already running, `start` restarts
it when the code on disk is newer; a red banner at the top of the page says the same thing. If the page looks like
yesterday's after a pull, press Ctrl+F5 once.

**After merging a PR during the day:** `git pull origin main`, then `python ui.py start` (it restarts the running
app). A picks run made before the restart used the old rules and parser.

## 2. Before the races

1. Download from TwinSpires into `data\pps\`: the **Ultimate PPs with QuickPlay Comments** as `<card>.pdf` and, if you
   take it, the **Power Play quick sheet** as `<card>q.pdf` (it turns on the key-race rule and the Brisnet benchmark).
   Or drop them on the Load tab, which saves them to the same place.
2. Pick the card in the selector at the top and press **Run picks**. The Desk shows each race's top three with rank,
   ML, score, win chance and A/B grade, the primary play, the other wagers, and the Pick 3 / Pick 4 tickets.
3. When scratches are posted: tick the scratched horses in the table (or paste the list on the Load tab, as
   `race:program` pairs such as `2:10, 4:2, 4:11`) and press **Re-run with scratches**. Also-eligibles draw in by
   themselves, lowest program first; when the track says otherwise, type it: `4:+12` puts AE or MTO #12 in,
   `4:-12` keeps it out. An AE that is not in shows its rank in brackets and is in no bet. That run is the one to
   bet from.
4. Click any horse for its rule-by-rule audit; click a race on the left to switch races.

Reading the bets: **Confidence** high = one horse, medium = two, low = contentious. "Price leg" on a Pick 3/4 means
the favourite is only a B. The other wagers list keys for a standout, boxes for a contentious race, win bets only on
overlays, and the favourite underneath when it looks beatable. Every win bet names the price to take ("take 2.6-1 or
better"): the morning line must be above the engine's fair odds plus a margin, or there is no win bet. A horse with
no morning line in the PPs gets no win bet counted; the line says what the board must show before you bet it.

Every run you make is also frozen under `data/out/snapshots/<card>/` and never rewritten. The run made before any
result was on file is the one the analysis scores ("pre-race"); the re-score after the charts arrive is shown as
"as-run" and is retrospective. Push `data/out` and the snapshots travel with the picks.

## 3. After the last race

1. Download each race's **chart PDF** ("View chart") into `data\results-png\<card>\`, named as downloaded
   (`20261106BELUSA1.pdf`). Charts carry every finisher, final odds, the track condition and all payouts.
   A payout-page screenshot (`r<N>.png`) works as a fallback for a race without a chart; it needs
   `pip install rapidocr_onnxruntime` once.
2. Press **Process results**. The app reads every chart, re-scores the card against the field that actually ran,
   back-tests, and writes `results\<card>.results.json` and `results\<card>.backtest.md`. Each race's After tab
   shows the finish, odds, payouts and what every suggested wager returned.
3. Analysis tab: hit/miss bars per track and overall, ROI by bet type, by confidence, by rule and by card.
4. Push the day's files (the charts themselves stay on your disk):

```powershell
git add results\ data\out\*.picks.json
```

```powershell
git commit -m "results: <card>"
```

```powershell
git push origin main
```

5. Done for the day:

```powershell
python ui.py stop
```

## 4. If something goes wrong

| Symptom | Fix |
|---|---|
| Card missing from the selector | its PP is not at `data\pps\<card>.pdf`; drop it on the Load tab, or check `Get-ChildItem data\pps` |
| "needs a run (picks)" when pressing Process results | press Run picks first |
| Process results reads nothing | the charts are not in `data\results-png\<card>\` (folder must match the PP name) |
| A control described here is not on the page | `git pull origin main`, `python ui.py stop`, `python ui.py start`, then Ctrl+F5 |
| "Check this result" banner on a race | a screenshot was read with doubts; compare with the image and correct it in the form below it |
| `git push` rejected ("fetch first") | `git pull origin main`, then push again |
| `results\` folder missing after a pull (OneDrive) | `git restore results`; consider keeping the clone outside OneDrive |
| Something else errors in the app | the message is in the toast at the bottom right and in `data\ui.log`; paste it to Claude |

Command-line equivalents, for scripting or for Claude to reproduce a run:

```powershell
python pick.py data\pps\<card>.pdf --sheet data\pps\<card>q.pdf --scratch "2:10, 4:2" -o data\out
```

```powershell
python ocr_results.py data\results-png\<card> results\<card>.results.json --card data\out\<card>.card.json --force
```

```powershell
python backtest.py data\out\<card>.picks.json results\<card>.results.json
```

## Never commit

PDFs (PPs, quick sheets, charts) and `*.card.json`. `.gitignore` blocks them; add files by name
(`git add results\ data\out\*.picks.json`) rather than `git add .`.

## Prediction timing and PASS

Contender rankings are retained even when the recommendation is PASS. WIN bets need a known price that
meets the printed minimum. Exotic keys/boxes and Pick 3/4 constructions are optional, unpriced scenarios;
they do not automatically become bets when a WIN price is rejected.

To record before-post timing, use the Load page's **Post times** map (race number to ISO timestamp with an
explicit timezone, such as `{"1":"2030-05-01T18:30:00Z"}`), or pass the same JSON file with `--post-times`.
Leave times unknown when they are unavailable. The default Analysis view includes only predictions made
before every supplied post time; choose timing-unverified or retrospective in the Evidence filter to inspect
other runs separately. Legacy pre-race filenames alone do not qualify. Snapshots retain their original policy
and stakes; evaluations are hypothetical recommendations, not executed-bet receipts.
