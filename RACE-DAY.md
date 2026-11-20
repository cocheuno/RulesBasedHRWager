# Race-day cheat sheet

Everything happens in Race Day Desk, the local app. PowerShell is used only to start it, stop it, and push the
results at the end of the day. All commands run from the `RulesBasedHRWager` folder.

`<card>` is the TwinSpires file code, e.g. `dmr1106y` (track + mmdd + y). The PP file, the results folder and the
results file all use it.

## 0. Set-up on Windows 11 (PowerShell), once

```powershell
cd $HOME\OneDrive\...\RulesBasedHRWager          # your clone
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt                   # pdfplumber; python-weather is optional
Copy-Item .env.example .env                        # then open .env and paste the PuntersEdge key
git config windows.appendAtomically false          # OneDrive: avoids "invalid write operation"
python ui.py start                                 # the Desk opens in the browser
```

`.env` is ignored by git. The app reads it at start: `PUNTERSEDGE_API_KEY` (or the file
`data\private\puntersedge.key`), `RACEDESK_WEATHER` and `RACEDESK_TOTE` (auto or off). If PowerShell refuses to run
the activation script: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

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
   If you take the **Racing Dudes** picks, save their dashboard page once ("Webpage, HTML only", after the page has
   loaded) and drop it in the Load tab's fourth box: it applies to every loaded card of the dates on the page and
   shows as a Racing Dudes column and chip. It is a benchmark; no rule reads it.
   If you have the **TimeformUS PPs** for the card, drop that PDF in the Load tab's third box: the Desk shows the
   Timeform rank and Top Fig beside the Brisnet rank and the Timeform picks on each race; the rules do not use it,
   and a file for another track or day is refused.
   Or drop them on the Load tab, which saves them to the same place.
2. Pick the card in the selector at the top and press **Run picks**. The Desk shows each race's top three with rank,
   ML, score, win chance and A/B grade, the primary play, the other wagers, and the Pick 3 / Pick 4 tickets.
3. Download Equibase's **late-changes XML** for the day (one file, every track racing) and drop it once in the Load
   tab's changes box: it is saved as `data\pps\latechanges_<date>.xml` and applied to every loaded card of that
   date (the toast names each card and its scratches). The per-track page still works: save Equibase's "Today's
   Race Day Changes" page for the track (browser: Save as, "Webpage, HTML only") and drop
   it on the Load tab. Its scratches join the list on the next run, and the morning track condition, rail setting
   and jockey changes are recorded on the run. Then, when scratches are posted: tick the scratched horses in the table (or paste the list on the Load tab, as
   `race:program` pairs such as `2:10, 4:2, 4:11`) and press **Re-run with scratches**. Also-eligibles draw in by
   themselves, lowest program first; when the track says otherwise, type it: `4:+12` puts AE or MTO #12 in,
   `4:-12` keeps it out. An AE that is not in shows its rank in brackets and is in no bet. That run is the one to
   bet from.
4. Click any horse for its rule-by-rule audit; click a race on the left to switch races.
5. Lines that start with **POLICY** say which suggested wagers the decisions table removed and why (lone speed,
   turf, firm turf, medium confidence, pools the track does not sell). **PLACE** and **SHOW** lines name the
   race's place and show candidates with the $2 price each needs.
6. The **Market** tab on a race shows what every source said and when: the morning line in its own column, the
   tote odds, pool dollars and public share with the provider's read time and age, the rule rank, the heuristic
   and market probabilities, break-even and minimum odds, the research gate and the frozen decision record, plus
   the stored odds and pool history. Stale or unavailable is shown as such, never as current.
7. **Weather**: below the bets, type the weather as the track or Equibase page prints it (any line order) and save
   it; the parsed values show beside the fetched forecast so a disagreement is visible. Rules do not read it.
8. **Best bets of the day** at the top of the Desk lists one or two win bets per card for the day, ranked by
   heuristic expected value at the morning line. It is a labelled view: in the frozen week it went 12 of 45, -13%.
9. Ticking a horse and unticking it leaves the Desk as it was: "re-run" appears only when the scratch set differs
   from the set the last run was made with.
10. If you are at the Desk near post time: press **Refresh tote** on the race. The Tote column shows the current
   win odds (to 1, as the track displays them) and each horse's share of the WIN pool; the wagers list shows the
   engine's minimum price beside the quote and how old the quote is. Mark a wager **Paper** if you intend it, or
   **Accepted (verified)** only if you actually placed it elsewhere. Each refresh costs 2 PuntersEdge credits; the
   app stops at the daily cap in `rules_config.json` (`tote.daily_credit_cap`). The key lives in
   `data\private\puntersedge.key` (one line) or the `PUNTERSEDGE_API_KEY` environment variable, never in git.

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
3. Analysis tab: hit/miss bars per track and overall, ROI by bet type, by confidence, by rule and by card; and the
   **Calibration and data watch** panel: how the pre-race predictions score against the charts (races, not bets)
   and how far each deferred capability is from its gate.
4. Push the day's files (the charts themselves stay on your disk):

```powershell
git add results\ data\out\*.picks.json data\out\snapshots\
```

   The snapshots are the pre-race record the evaluation and the data watch count; they must be pushed too.
   To refresh `docs\EVALUATION.md` and `docs\DATA_WATCH.md` with the day's races:

```powershell
python -m handicapper.evaluation report --write; python -m handicapper.evaluation watch --write
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
| "refused: this PP is not <card>'s" when dropping PPs | The open card already has picks or results and the file is another day's or track's. Type the new card code in **New card code** first, then drop the file again |
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
