# 🪙 Crypto High-Risk Strategy — Skill & Knowledge Base

> **AI Agent / Developer: read this file first when entering the project.**

---

## 1. Mission

Turn a 500 USDT high-risk account into a structured research + execution workflow
for Binance USDⓈ-M perpetual futures. Focus on small-cap momentum, breakout
continuation, and shorting failed expansion.

| Item | Value |
|------|-------|
| **Platform** | Binance USDⓈ-M Perpetual Futures |
| **Capital** | 500 USDT |
| **Risk** | 🔴 Extreme (accept total loss, pursue 10x-100x) |
| **Leverage** | 1x / 3x / 5x dynamic |
| **Language** | Python 3 (venv, no global packages) |

---

## 2. Setup Taxonomy (4 Setups)

### Setup A: Long Breakout Continuation
Price breaks a clear local high with expanding volume.
- Volume materially above baseline
- RSI > 60, confirming momentum
- Stop below breakout level

### Setup B: Long First Pullback
Strong impulse already occurred; first controlled retracement.
- EMA9 > EMA21 (uptrend intact)
- Price pulls back to EMA9, RSI cooling < 50
- Better asymmetry than a full chase

### Setup C: Short Failed Breakout
Price pushes through resistance, can't hold, re-enters range.
- Failed hold is clear on candle structure
- Short trigger below reclaimed level
- Tight stop above failed high

### Setup D: Short Parabolic Exhaustion
Late-stage vertical move becomes unstable.
- Abnormal volume expansion + bearish candle, OR
- RSI > 80 with volume spike
- Reversal trigger exists (not blind guess)

---

## 3. Leverage & Risk Bands

| Leverage | When to Use |
|----------|-------------|
| **1x** | Discovery trades, uncertain structure, loose stops |
| **3x** | Default aggressive tier, clear setup |
| **5x** | Narrow-risk, high-clarity setups only (max 1 position) |

### Hard Risk Rules (R1-R8) — NEVER VIOLATED

| # | Rule | Detail |
|---|------|--------|
| R1 | Single trade max loss ≤ 15% | Of account equity |
| R2 | Max 3 concurrent positions | Diversify direction risk |
| R3 | Daily max loss ≤ 40% | Stop trading for the day |
| R4 | 3 consecutive stop-losses → 2h cooldown | Prevent tilt |
| R5 | Balance ≤ 200U → 1x only | Survival mode until 400U |
| R6 | Balance ≥ 2000U → withdraw 50% | Lock in profits |
| R7 | Every trade MUST have a stop-loss | No exceptions |
| R8 | No stop-less averaging down | Only add with protection |

---

## 4. Architecture

```
Crpyto_High_Risk_Strategy/
├── config/
│   ├── settings.py          # Dataclass config (leverage, risk, entry params)
│   └── pairs_whitelist.py   # Blacklist/whitelist management
├── core/
│   ├── exchange.py          # ccxt Binance wrapper (singleton)
│   ├── scanner.py           # Full-market volume/price scan
│   ├── signals.py           # Technical indicators + signal generation
│   ├── strategy.py          # Trade decision engine (Setup A/B/C/D)
│   ├── risk_manager.py      # R1-R8 hard risk rules enforcement
│   ├── executor.py          # Live order placement + SL/TP
│   └── paper_trader.py      # Paper trading simulator
├── scripts/
│   ├── run_scanner.py       # Main pipeline: scan→signal→decide→execute
│   └── run_paper.py         # Paper trading CLI
├── utils/
│   ├── logger.py            # Structured logging (loguru)
│   └── helpers.py           # Utility functions
├── data/                    # Kline cache, backtest results
├── logs/                    # Trade + system logs (auto-created)
├── tests/                   # Unit tests
├── handover/                # Agent handover documents
├── task_v1.md               # Original vision
└── skill.md                 # This file
```

---

## 5. Data Flow

```
[Binance API] ──tickers──▶ [Scanner]
                               │ top gainers/losers
                               ▼
                         [Signals Engine]
                         EMA9/21, RSI14, volume ratio
                         Setup A/B/C/D detection
                               │ actionable signals
                               ▼
                         [Strategy Engine]
                         direction + leverage + SL/TP
                               │ trade decision
                               ▼
                         [Risk Manager]
                         R1-R8 enforcement
                            /        \
                          OK          Blocked → log & skip
                          │
                          ▼
                    [Executor / Paper Trader]
                    place orders + set SL/TP
                          │
                          ▼
                    [Logger] trade records + notifications
```

---

## 6. Quick Start

```bash
# Setup
cd Crpyto_High_Risk_Strategy
python -m venv venv
.\venv\Scripts\activate          # Windows
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your Binance API keys

# Paper trading scan (safe, no real money)
python -m scripts.run_scanner --once

# Paper trade management
python -m scripts.run_paper status
python -m scripts.run_paper open BTC/USDT:USDT LONG 65000 100 3

# Live mode (CAUTION: real money!)
python -m scripts.run_scanner --live --once
```

---

## 7. API Security
- Keys ONLY in `.env` (never in code)
- `.env` in `.gitignore`
- Recommend IP whitelist on Binance
- API permissions: Read + Futures Trade only (NO withdrawal)
- Default: testnet=true

---

## 8. Development Rules
- PEP 8 + type hints
- Chinese commit messages: `[module] description`
- Handover docs updated after each task
- "存檔" / "交接" / "完畢" → auto git commit

---

## 9. Backtest Requirements (before live)

| Metric | Minimum |
|--------|---------|
| Win Rate | ≥ 40% |
| Profit Factor | ≥ 2.5:1 |
| Sharpe Ratio | ≥ 1.0 |
| Test Period | ≥ 30 days |

---

> **📌 High risk ≠ no rules. Every trade needs a signal, a stop-loss, and a log.**
