# Race-day cheat sheet

All commands run in PowerShell from the `RulesBasedHRWager` folder.
`<card>` is the TwinSpires file code, e.g. `dmr1106y` (track + mmdd + y). Use it everywhere: PDF name,
screenshot folder, results file.

## 0. Once per day, before anything else

```powershell
git pull origin main
```

If `git status` ever shows files deleted that you did not delete (OneDrive), restore them first:

```powershell
git restore .
```

## 1. Morning: get the selections

1. Download **Ultimate PPs with QuickPlay Comments** from TwinSpires into `data\pps\<card>.pdf`.
2. First look (summary only: top three per race, primary play, other wagers, Pick 3/4 tickets):

```powershell
python pick.py data\pps\<card>.pdf --detail 0
```

## 2. After scratches are posted: the run you bet from

Scratches are `race:program` pairs, in quotes, comma-separated. Also-eligibles draw in automatically.

```powershell
python pick.py data\pps\<card>.pdf --scratch "2:10, 4:2, 4:11, 7:13" -o data\out
```

If you also downloaded the Power Play quick sheet (`<card>q.pdf`), add `--sheet data\pps\<card>q.pdf`: it turns on
the key-race rule (F16) and lets the back-test compare the engine with Brisnet's own picks.

This prints the full report and writes `data\out\<card>.picks.md` (summary first, then every rule hit) and
`data\out\<card>.picks.json` (needed for the back-test).  Re-run it if more scratches come in.

Optional, during the card: once three or more races on a surface are done, enter them (step 4) and re-run
with `--results results\<card>.results.json` to let the same-day bias rule (P10) see them.

Useful variants:

| Want | Command |
|---|---|
| One race, every rule hit | `python pick.py data\pps\<card>.pdf --race 6 --detail 2` |
| Pick 4 shaped to a $48 budget | `python pick.py data\pps\<card>.pdf --budget4 48 --detail 0` |
| Skip the Pick 3/4 section | add `--no-multi` |
| Re-score without re-parsing the PDF | use `data\out\<card>.card.json` in place of the PDF |

## 3. Reading the output

- **Wagering summary** (top of the report): per race the top three with rank, ML, score, win chance and A/B
  grade; the primary play; other wagers (exacta/trifecta keys or boxes, win only on overlays, "chalk
  underneath" when the favourite looks beatable, daily double with the next race's A horses).
- **Pick 3 / Pick 4**: the recommended window with its tickets and cost; "single" legs are one horse,
  "price leg" means the favourite is only a B.
- **Confidence** high = single-horse play; medium = two horses; low = contentious, spread or pass.
- **Race details** below the summary: the rule-by-rule audit for every horse, if you want to know why.

## 4. After the last race: hand the results to Claude

1. Save each race's **PAYOUTS** page screenshot as `data\results-png\<card>\r<N>.png` (r1.png, r2.png, ...).
2. Push the screenshots and the picks file:

```powershell
git add data\results-png data\out\*.picks.json
```

```powershell
git commit -m "<card>: results screenshots"
```

```powershell
git push origin main
```

3. Tell Claude: **"process <card>"**.  Claude transcribes the screenshots into
   `results\<card>.results.json`, runs the back-test, commits `results\<card>.results.json` and
   `results\<card>.backtest.md`, pushes, and reports how the selections and tickets did.
4. Next morning's `git pull` brings those files down.

## 4b. Doing the results yourself instead (optional)

One line per race, straight off the payout page. First race of a card needs `--track` and `--date`:

```powershell
python addresult.py results\<card>.results.json 1 1/6/4/3 win=5.20 place=1:3.40,6:9.20 show=1:2.10,6:3.20,4:2.10 exacta=1:1/6:17.30 trifecta=0.5:1/6/4:13.50 super=0.1:1/6/4/3:12.46 --track "Del Mar" --date 2026-11-06
```

Then:

```powershell
python backtest.py data\out\<card>.picks.json results\<card>.results.json
```

```powershell
git add results\
```

```powershell
git commit -m "results: <card>"
```

```powershell
git push origin main
```

## 5. Things that go wrong

| Symptom | Fix |
|---|---|
| `No such file or directory: data/pps/<card>.pdf` | PDF not copied in, or named differently: `Get-ChildItem data\pps` |
| `results\` folder missing after a pull | OneDrive removed it: `git restore results` (consider moving the clone out of OneDrive) |
| `mkdir -p` error | PowerShell: `New-Item -ItemType Directory -Force -Path data\pps` |
| `RULE ERROR` in a horse's audit | a rule hit bad data; send Claude the race number, the run still completes |
| `parser warning: page N: no race header found` | normal for the wager-menu page; ignore |

## Never commit

PDFs, `*.card.json`, anything else in `data\pps`.  `.gitignore` blocks them, but add files by name
(`git add results\`, `git add data\results-png`) rather than `git add .`.
