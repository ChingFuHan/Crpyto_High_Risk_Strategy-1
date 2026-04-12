# Session Context Summary — 2026-04-12

## Repo / Git
- Repo path: `C:\Users\User\Documents\Crpyto_High_Risk_Strategy`
- Current branch: `master`
- Working tree was clean at handoff time
- Latest pushed commits:
  - `2c7116c` `[backtest] 補年化夏普卡馬與交接紀錄`
  - `9bbdf7a` `[backtest] 新增3x多頭優化流程與回測摘要`
- Remote still redirects. New GitHub location:
  - `https://github.com/ChingFuHan/Crpyto_High_Risk_Strategy-1.git`
- Recommended one-time fix:
  - `git remote set-url origin https://github.com/ChingFuHan/Crpyto_High_Risk_Strategy-1.git`

## What Was Done In This Session
- Audited the merged project and fixed a real runtime break in `core/signals.py`
  - `ta` API compatibility fix (`n=` vs `window=`)
  - safer indicator math for zero-volume / zero-range candles
  - breakout reference changed to prior 20-bar high/low
- Fixed `core/risk_manager.py` balance accounting on close
- Added tests for signal/risk behavior
- Verified:
  - `python -m scripts.run_scanner --once` runs without crashing
  - pytest passed after fixes

## Backtest Infrastructure Upgrades
- `core/backtester.py`
  - now supports configurable:
    - fixed leverage
    - min margin
    - capital floor
    - standard symbol filter
    - symbol blacklist
    - reusable prepared-data runs
  - now reports:
    - total return
    - annualized return
    - Sharpe ratio
    - Calmar ratio
- `scripts/run_backtest.py`
  - exposes entry / exit / universe / leverage params via CLI
  - supports output prefix to avoid overwriting previous runs
- `scripts/optimize_long_only_3x.py`
  - added for repeatable parameter sweeps
  - supports resume and incremental result saving
- Tests:
  - `tests/test_backtester.py` added
  - latest known test status: `python -m pytest -q` -> `8 passed`

## Multi-Timeframe Data Availability
- Added full raw lower-timeframe history for the same symbol universe as `1h`
- Directories now available:
  - `data/history/15m`
  - `data/history/5m`
- Universe parity check:
  - `1h`: `538` symbols
  - `15m`: `538` symbols
  - `5m`: `538` symbols
  - no missing / extra symbols between `1h`, `15m`, and `5m`
- Approximate disk usage:
  - `1h`: `0.585 GB`
  - `15m`: `2.316 GB`
  - `5m`: `6.891 GB`
- `scripts/download_history.py` was improved for this:
  - added CLI `--delay`
  - made console output ASCII-safe so Windows `cp950` does not crash on rate-limit logs or non-ASCII symbol names

## Important Findings
- Strategy under test: `only long`, fixed `3x`, max `5` concurrent symbols
- Entry tightening alone did NOT help
  - stricter entry filters generally degraded results badly
  - see:
    - `data/optimization_long_only_3x_max5_broad_narrow1.json`
- Exit tuning mattered much more than entry tuning
  - useful result files:
    - `data/optimization_long_only_3x_max5_exit_tuning.json`
    - `data/optimization_long_only_3x_max5_exit_refine.json`

## Best Current Repro
Use this exact command:

```bash
python -m scripts.run_backtest --out-prefix tuned_long_only_3x_max5_v1 --fixed-lev 3 --max-pos 5 --vol-mult 1.5 --rsi-min 52 --rsi-max 80 --close-ratio 0.55 --min-margin 1 --capital-floor 10 --sl-atr-3x 3.0 --trail-act 0.04 --trail-dist 0.018 --max-hold 96 --rsi-exit-max 85 --standard-symbols --exclude-symbols BTCDOMUSDT USDCUSDT
```

## Best Current Metrics
- Final capital: `1517.94 USDT`
- Total return: `+203.59%`
- Annualized return: `+18.36%`
- Sharpe ratio: `0.61`
- Calmar ratio: `0.70`
- Profit factor: `1.05`
- Win rate: `61.1%`
- Max drawdown: `26.4%`
- Total trades: `9850`

## Best Run Artifacts
- `data/tuned_long_only_3x_max5_v1_summary.json`
- `data/tuned_long_only_3x_max5_v1_trades.csv`
- `data/tuned_long_only_3x_max5_v1_equity.csv`

## Walk-Forward Validation
- Added reusable date-range slicing for prepared market snapshots
- `scripts/run_backtest.py` now accepts:
  - `--start-date`
  - `--end-date`
  - and writes `{prefix}_summary.json`
- Tested split:
  - train: `2019-09-09` to `2023-12-31`
  - validate: `2024-01-01` to `2026-04-11`

### Walk-Forward Metrics
- Train (`wf_tuned_long_only_3x_max5_v1_train`)
  - Final capital: `1543.40 USDT`
  - Return: `+208.68%`
  - Annualized return: `+29.88%`
  - Sharpe ratio: `0.76`
  - Calmar ratio: `1.13`
  - Profit factor: `1.06`
  - Max drawdown: `26.4%`
  - Trades: `5751`
- Validate (`wf_tuned_long_only_3x_max5_v1_validate`)
  - Final capital: `559.26 USDT`
  - Return: `+11.85%`
  - Annualized return: `+5.04%`
  - Sharpe ratio: `0.39`
  - Calmar ratio: `0.19`
  - Profit factor: `1.02`
  - Max drawdown: `26.5%`
  - Trades: `4107`

### Interpretation
- Out-of-sample performance stayed positive, so the tuned configuration did not fully collapse under walk-forward validation
- But the validation edge is much weaker than in-sample
- Important caveat:
  - training window loaded `180` enabled symbols
  - validation window loaded `533` enabled symbols
  - this is realistic as a forward test, but it is not a fixed-universe stability test

### Walk-Forward Artifacts
- `data/wf_tuned_long_only_3x_max5_v1_train_summary.json`
- `data/wf_tuned_long_only_3x_max5_v1_train_trades.csv`
- `data/wf_tuned_long_only_3x_max5_v1_train_equity.csv`
- `data/wf_tuned_long_only_3x_max5_v1_validate_summary.json`
- `data/wf_tuned_long_only_3x_max5_v1_validate_trades.csv`
- `data/wf_tuned_long_only_3x_max5_v1_validate_equity.csv`
- `data/walkforward_tuned_long_only_3x_max5_v1.json`

## Earlier Comparison Runs
- Baseline negative run:
  - `data/backtest_summary_long_only_3x_max5.json`
  - around `-45.58%`
- Min-margin-to-1 with lock:
  - `data/backtest_summary_long_only_3x_max5_min1_lock.json`
  - around `-50.23%`
- Min-margin-to-1 without profit lock:
  - `data/backtest_summary_long_only_3x_max5_min1_nolock.json`
  - around `-98.10%`
- Conclusion:
  - profit lock helps survival
  - but positive expectancy came from exit tuning, not from disabling lock or simply loosening entry constraints

## Current Project State
- Scanner / paper pipeline is runnable
- Backtest tooling is materially improved and pushed
- Walk-forward validation completed for the current best long-only config
- Raw market history is now available for `1h`, `15m`, and `5m`
- Handover log updated:
  - `handover/CHANGELOG.md`
- Original project vision still centered on:
  - Binance USDT-M futures
  - small-cap momentum
  - aggressive risk profile

## Recommended Next Steps
1. Build the multi-timeframe data plumbing on top of the new `15m` / `5m` raw history
   - decide how `1h` / `15m` / `5m` should align at feature-join time
   - add reusable loaders / resamplers or synchronized readers before strategy changes
2. Re-run walk-forward on a fixed universe or add a listing-age filter
   - current walk-forward used `180` enabled train symbols vs `533` validate symbols
   - use this to separate true parameter decay from symbol-universe drift
3. Compare best long-only config vs:
   - long+short
   - short-only failed-breakout logic
4. If continuing on same machine, update `origin` to the new GitHub URL

## If Starting A New Chat Window
Paste this:

```text
Continue work in repo C:\Users\User\Documents\Crpyto_High_Risk_Strategy.
Read handover/SESSION_CONTEXT_2026-04-12.md first, then handover/CHANGELOG.md.
Current best backtest is tuned_long_only_3x_max5_v1.
Walk-forward validation is done, and raw 15m/5m history has been downloaded. Next task should focus on multi-timeframe data plumbing or fixed-universe validation unless I redirect you.
```
