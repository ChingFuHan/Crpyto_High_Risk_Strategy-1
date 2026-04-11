# Handover / 智慧傳承

## 2026-04-11 — Audit / Validate / Fix Pass

### Findings Fixed
- Fixed `core/signals.py` `ta` API incompatibility: local environment uses legacy `n=` parameters, which broke `python -m scripts.run_scanner --once`
- Hardened indicator computation against zero-volume / zero-range candles to avoid `inf` and unstable shadow ratios
- Changed breakout reference levels to use the prior 20-bar high/low instead of including the current candle, which makes Setup A/C detection internally consistent
- Fixed `core/risk_manager.py` balance accounting so closing a position returns locked margin plus realized PnL

### Validation
- `python -m pytest -q` → 3 passed
- `python -m scripts.run_scanner --once` → completed scan/analyze cycle without crashing
- `py_compile` check passed for repo Python files

### Residual Risks
- Live order placement path was not exercised; only paper/default scanner flow was validated
- Paper mode still needs a fuller position-management loop if you want automatic TP/SL lifecycle simulation

## 2026-04-12 — Long-Only 3x Backtest Optimization

### What Changed
- Extended `core/backtester.py` with reusable prepared-data runs plus configurable leverage, margin floor, capital floor, and symbol-universe filtering
- Extended `scripts/run_backtest.py` to expose entry/exit tuning parameters and output prefixes
- Added `scripts/optimize_long_only_3x.py` for repeatable parameter sweeps
- Added report metrics for annualized return, Sharpe ratio, and Calmar ratio

### Key Result
- Tightening entry filters alone was a dead end: the best broad-universe strict-entry run remained the baseline, while stricter filters degraded to roughly `-98%`
- Exit tuning mattered much more than entry tightening

### Current Best Public Repro
Command:
`python -m scripts.run_backtest --out-prefix tuned_long_only_3x_max5_v1 --fixed-lev 3 --max-pos 5 --vol-mult 1.5 --rsi-min 52 --rsi-max 80 --close-ratio 0.55 --min-margin 1 --capital-floor 10 --sl-atr-3x 3.0 --trail-act 0.04 --trail-dist 0.018 --max-hold 96 --rsi-exit-max 85 --standard-symbols --exclude-symbols BTCDOMUSDT USDCUSDT`

### Best Metrics So Far
- Final capital: `1517.94 USDT`
- Return: `+203.59%`
- Annualized return: `+18.36%`
- Sharpe ratio: `0.61`
- Calmar ratio: `0.70`
- Profit factor: `1.05`
- Win rate: `61.1%`
- Max drawdown: `26.4%`
- Trades: `9850`

### Validation
- `python -m pytest -q` → 6 passed
- Recomputed the best public repro after adding risk-adjusted metrics; headline results stayed consistent

### Artifacts
- `data/tuned_long_only_3x_max5_v1_trades.csv`
- `data/tuned_long_only_3x_max5_v1_equity.csv`
- `data/optimization_long_only_3x_max5_exit_tuning.json`
- `data/optimization_long_only_3x_max5_exit_refine.json`

## 2026-04-11 — Project Merge & Foundation Build

### What Was Done
- Merged two separate agent projects (Copilot + Codex) into a unified codebase
- **From Copilot**: adopted modular architecture, dataclass config, R1-R8 risk rules
- **From Codex**: integrated working scan/analyze/paper-trade logic into proper modules
- **New additions**: 4-setup strategy engine (A/B/C/D), improved liquidation math, fee handling

### Modules Completed
| Module | Status | Source |
|--------|--------|--------|
| config/settings.py | ✅ | Copilot (enhanced) |
| config/pairs_whitelist.py | ✅ | Copilot |
| core/exchange.py | ✅ | New (ccxt pattern from Codex) |
| core/scanner.py | ✅ | Codex scan_pump.py (refactored) |
| core/signals.py | ✅ | Codex analyze_kline.py (refactored + 4 setups) |
| core/strategy.py | ✅ | New (decision engine) |
| core/risk_manager.py | ✅ | New (R1-R8 implementation) |
| core/executor.py | ✅ | New (live order + SL/TP) |
| core/paper_trader.py | ✅ | Codex paper_trade.py (improved) |
| utils/logger.py | ✅ | New (loguru) |
| utils/helpers.py | ✅ | New |
| scripts/run_scanner.py | ✅ | New (full pipeline) |
| scripts/run_paper.py | ✅ | New (paper trade CLI) |
| skill.md | ✅ | Merged from both |

### Current State
- All core modules implemented and import-tested
- Paper trading mode is the default (safe)
- Testnet mode is the default (safe)
- No live trading has been performed

### Next Steps
1. Run full integration test with Binance testnet API keys
2. Build backtest harness (Phase 4 from original roadmap)
3. Add unit tests for signals and risk manager
4. Add Telegram notification support
5. Paper trade for minimum 1 week before considering live

### Key Decisions
- Used `ccxt` instead of `python-binance` for better abstraction
- Singleton exchange pattern to avoid multiple connections
- Maintenance margin rate (2%) used in liquidation calculation instead of naive 1/leverage
- Trading fees (0.04%) deducted in paper trader for realism
- Max 1 concurrent 5x position (from Codex strategy framework)
