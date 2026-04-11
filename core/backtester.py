"""
Backtester — multi-asset momentum-chase (追高) engine.

Long-only | 500 USDT | Max 5 concurrent positions | Leverage 3x–10x

Reads CSV directory of files with columns: da,op,hi,lo,cl,vol
Produces: trade log CSV, equity curve CSV, and a summary dict.

Key features (v2):
  - BTC trend regime filter (only trade when BTC above EMA-200)
  - Drawdown circuit breaker (pause at -30 %, resume at -15 %)
  - Liquidation modelling (loss capped at margin)
  - Entry fees tracked in trade PnL
  - Report uses actual equity change

Usage (via run_backtest.py):
    python -m scripts.run_backtest
    python -m scripts.run_backtest --data data/history/1h --capital 500
"""

import os
import re
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BacktestConfig:
    initial_capital: float = 500.0
    max_positions: int = 5
    fee_rate: float = 0.0004            # 0.04 % taker per side
    fixed_leverage: Optional[int] = None
    verbose: bool = True

    # Leverage tiers: (min_score, leverage)  — checked high→low
    leverage_tiers: list = field(default_factory=lambda: [
        (0.85, 10),
        (0.70, 7),
        (0.55, 5),
        (0.0, 3),
    ])

    # ── indicators ────────────────────────────────────────────────────────
    ema_fast: int = 9
    ema_mid: int = 21
    ema_slow: int = 50
    ema_regime: int = 200               # BTC regime filter
    rsi_period: int = 14
    atr_period: int = 14
    vol_ma_period: int = 20
    breakout_lookback: int = 20

    # ── entry thresholds ──────────────────────────────────────────────────
    rsi_entry_min: float = 52.0
    rsi_entry_max: float = 80.0
    volume_mult: float = 1.5
    min_close_ratio: float = 0.55       # candle body bullishness

    # ── position sizing ──────────────────────────────────────────────────
    risk_per_trade: float = 0.15        # 15 % of capital per slot
    min_margin: float = 5.0
    capital_floor: float = 10.0

    # ── exit parameters ───────────────────────────────────────────────────
    sl_atr_mult: dict = field(default_factory=lambda: {
        3: 3.0, 5: 2.5, 7: 2.0, 10: 1.5,
    })
    trailing_act_pct: float = 0.06      # activate trailing at +6 %
    trailing_dist_pct: float = 0.025    # 2.5 % trail distance
    rsi_exit_max: float = 85.0
    max_hold_bars: int = 96             # 96 h for 1h candles

    # ── portfolio-level risk ─────────────────────────────────────────────
    equity_trail_pct: float = 0.25      # close all if equity drops 25 % from peak
    profit_lock_mult: float = 1.5       # lock gains when equity hits 1.5x base
    profit_lock_ratio: float = 0.4      # fraction of excess to lock each time

    # ── cooldown ──────────────────────────────────────────────────────────
    cooldown_bars: int = 5

    # ── universe filter ───────────────────────────────────────────────────
    require_standard_symbols: bool = False
    exclude_symbols: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# Data records
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Position:
    symbol: str
    entry_price: float
    entry_time: str
    leverage: int
    margin: float
    notional: float
    stop_loss: float
    trailing_stop: float
    highest_price: float
    entry_fee: float = 0.0              # tracked for accurate PnL
    bars_held: int = 0


@dataclass
class Trade:
    symbol: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    leverage: int
    margin: float
    pnl: float
    pnl_pct: float
    exit_reason: str
    bars_held: int


# ═══════════════════════════════════════════════════════════════════════════
# Engine
# ═══════════════════════════════════════════════════════════════════════════

class Backtester:
    """Event-driven multi-asset backtester with pre-computed signals."""

    def __init__(self, config: BacktestConfig | None = None):
        self.cfg = config or BacktestConfig()
        self._standard_symbol_re = re.compile(r"^[A-Z0-9]+USDT$")
        self._reset_state()

    def _reset_state(self):
        self.capital: float = self.cfg.initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.equity_curve: List[dict] = []
        self._equity_points: List[float] = []
        self.cooldowns: Dict[str, int] = {}
        self.peak_equity: float = self.cfg.initial_capital
        self.max_dd: float = 0.0
        self.paused: bool = False        # equity trail stop
        self.locked_profit: float = 0.0  # profit withdrawn & locked
        self.lock_base: float = self.cfg.initial_capital  # next lock level
        self._timeline_start: Optional[pd.Timestamp] = None
        self._timeline_end: Optional[pd.Timestamp] = None
        self._bar_seconds: Optional[float] = None

    # ── vectorised indicator computation ──────────────────────────────────

    @staticmethod
    def _ema(s: pd.Series, span: int) -> pd.Series:
        return s.ewm(span=span, adjust=False).mean()

    def _is_symbol_enabled(self, symbol: str) -> bool:
        if symbol in set(self.cfg.exclude_symbols):
            return False
        if self.cfg.require_standard_symbols and not self._standard_symbol_re.match(symbol):
            return False
        return True

    def _build_entry_mask(self, df: pd.DataFrame) -> pd.Series:
        c = self.cfg
        return (
            df["trend_up"]
            & df["rsi"].between(c.rsi_entry_min, c.rsi_entry_max)
            & (df["vol_r"] >= c.volume_mult)
            & (df["cl"].astype(float) > df["prev_hi"])
            & (df["cr"] >= c.min_close_ratio)
        ).fillna(False)

    def _entry_signal(self, data: dict, idx: int) -> bool:
        prev_hi = data["prev_hi"][idx]
        rsi = data["rsi"][idx]
        vol_r = data["vol_r"][idx]
        close_ratio = data["cr"][idx]
        close_price = data["cl"][idx]
        if np.isnan(prev_hi) or np.isnan(rsi) or np.isnan(vol_r) or np.isnan(close_ratio):
            return False
        return bool(
            data["trend_up"][idx]
            and self.cfg.rsi_entry_min <= rsi <= self.cfg.rsi_entry_max
            and vol_r >= self.cfg.volume_mult
            and close_price > prev_hi
            and close_ratio >= self.cfg.min_close_ratio
        )

    @staticmethod
    def _safe_round_ratio(value: Optional[float]):
        if value is None or np.isnan(value):
            return None
        if np.isinf(value):
            return "∞"
        return round(float(value), 2)

    def _compute_period_stats(self, initial_capital: float, final_capital: float) -> dict:
        if (
            self._timeline_start is None
            or self._timeline_end is None
            or self._timeline_end <= self._timeline_start
        ):
            return {
                "annualized_return_pct": None,
                "sharpe_ratio": None,
                "calmar_ratio": None,
            }

        elapsed_seconds = (self._timeline_end - self._timeline_start).total_seconds()
        years = elapsed_seconds / (365.25 * 24 * 3600)
        if years <= 0:
            annualized_return = None
        elif final_capital <= 0:
            annualized_return = -1.0
        else:
            annualized_return = (final_capital / initial_capital) ** (1 / years) - 1

        sharpe_ratio = None
        if self._bar_seconds and self._bar_seconds > 0 and len(self._equity_points) >= 2:
            equity = np.asarray(self._equity_points, dtype=float)
            periodic_returns = np.diff(equity) / equity[:-1]
            periodic_returns = periodic_returns[np.isfinite(periodic_returns)]
            if len(periodic_returns) >= 2:
                ret_std = float(np.std(periodic_returns, ddof=1))
                if ret_std == 0:
                    ret_mean = float(np.mean(periodic_returns))
                    sharpe_ratio = np.inf if ret_mean > 0 else None
                else:
                    periods_per_year = (365.25 * 24 * 3600) / self._bar_seconds
                    sharpe_ratio = (
                        float(np.mean(periodic_returns)) / ret_std
                    ) * np.sqrt(periods_per_year)

        max_dd_decimal = float(self.max_dd)
        calmar_ratio = None
        if annualized_return is not None:
            if max_dd_decimal == 0:
                calmar_ratio = np.inf if annualized_return > 0 else None
            else:
                calmar_ratio = annualized_return / max_dd_decimal

        return {
            "annualized_return_pct": None if annualized_return is None else round(annualized_return * 100, 2),
            "sharpe_ratio": self._safe_round_ratio(sharpe_ratio),
            "calmar_ratio": self._safe_round_ratio(calmar_ratio),
        }

    def _compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return *df* enriched with indicators, entry flag, and score."""
        df = df.copy()
        cl = df["cl"].astype(float)
        hi = df["hi"].astype(float)
        lo = df["lo"].astype(float)
        vol = df["vol"].astype(float)
        c = self.cfg

        # EMAs
        df["ema_f"] = self._ema(cl, c.ema_fast)
        df["ema_m"] = self._ema(cl, c.ema_mid)
        df["ema_s"] = self._ema(cl, c.ema_slow)

        # RSI (Wilder)
        delta = cl.diff()
        up = delta.clip(lower=0)
        dn = (-delta).clip(lower=0)
        a_up = up.ewm(alpha=1 / c.rsi_period, min_periods=c.rsi_period, adjust=False).mean()
        a_dn = dn.ewm(alpha=1 / c.rsi_period, min_periods=c.rsi_period, adjust=False).mean()
        df["rsi"] = 100 - 100 / (1 + a_up / a_dn.replace(0, np.nan))

        # ATR
        tr = pd.concat([
            hi - lo,
            (hi - cl.shift(1)).abs(),
            (lo - cl.shift(1)).abs(),
        ], axis=1).max(axis=1)
        df["atr"] = tr.rolling(c.atr_period).mean()

        # Volume ratio
        vol_ma = vol.rolling(c.vol_ma_period).mean()
        df["vol_r"] = (vol / vol_ma.replace(0, np.nan)).replace(
            [np.inf, -np.inf], np.nan
        )

        # Breakout reference (prior N-bar highest close)
        df["prev_hi"] = cl.rolling(c.breakout_lookback).max().shift(1)

        # Close-within-candle ratio (1 = at high, 0 = at low)
        rng = (hi - lo).replace(0, np.nan)
        df["cr"] = ((cl - lo) / rng).fillna(0.5)

        # Rate of change (10 bars)
        df["roc"] = cl.pct_change(10)

        # ── entry signal (vectorised boolean) ─────────────────────────────
        df["trend_up"] = (
            (cl > df["ema_f"])
            & (df["ema_f"] > df["ema_m"])
            & (df["ema_m"] > df["ema_s"])
        ).fillna(False)
        df["entry"] = self._build_entry_mask(df)

        # ── momentum score (0–1) ─────────────────────────────────────────
        trend = ((df["ema_f"] - df["ema_s"]) / df["ema_s"]).clip(0, 0.30)
        rsi_s = ((df["rsi"] - 50) / 35).clip(0, 0.25)
        vol_s = ((df["vol_r"] - 1.5) / 8).clip(0, 0.25)
        roc_s = (df["roc"] * 5).clip(0, 0.20)
        df["score"] = (trend + rsi_s + vol_s + roc_s).clip(0, 1.0)

        return df

    def _compute_regime(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute BTC regime filter: price > EMA-regime."""
        df = df.copy()
        cl = df["cl"].astype(float)
        ema = self._ema(cl, self.cfg.ema_regime)
        df["ema_regime"] = ema
        df["regime_bull"] = cl > ema
        return df

    # ── leverage ──────────────────────────────────────────────────────────

    def _lev(self, score: float) -> int:
        if self.cfg.fixed_leverage is not None:
            return self.cfg.fixed_leverage
        for thresh, lev in self.cfg.leverage_tiers:
            if score >= thresh:
                return lev
        return 3

    # ── position management ───────────────────────────────────────────────

    def _open(self, sym: str, price: float, atr: float, score: float, da: str):
        slots = self.cfg.max_positions - len(self.positions)
        if slots <= 0 or self.capital < self.cfg.capital_floor:
            return
        lev = self._lev(score)
        margin = round(min(self.capital * self.cfg.risk_per_trade,
                           self.capital / slots), 4)
        if margin < self.cfg.min_margin:
            return

        notional = margin * lev
        fee = notional * self.cfg.fee_rate
        sl_mult = self.cfg.sl_atr_mult.get(lev, 2.5)
        sl = price - sl_mult * atr

        self.capital -= (margin + fee)
        self.positions[sym] = Position(
            symbol=sym, entry_price=price, entry_time=da,
            leverage=lev, margin=margin, notional=notional,
            stop_loss=sl, trailing_stop=sl, highest_price=price,
            entry_fee=fee,
        )

    def _close(self, sym: str, exit_price: float, da: str, reason: str):
        pos = self.positions.pop(sym)
        chg = (exit_price - pos.entry_price) / pos.entry_price
        raw_pnl = pos.notional * chg
        exit_not = pos.notional * (exit_price / pos.entry_price)
        exit_fee = abs(exit_not) * self.cfg.fee_rate
        pnl = raw_pnl - exit_fee - pos.entry_fee

        # Liquidation: loss cannot exceed margin
        returned = pos.margin + pnl
        if returned < 0:
            pnl = -pos.margin
            returned = 0.0
            reason = "liquidation"

        self.capital += returned

        self.trades.append(Trade(
            symbol=sym, entry_time=pos.entry_time, exit_time=da,
            entry_price=pos.entry_price, exit_price=exit_price,
            leverage=pos.leverage, margin=pos.margin,
            pnl=round(pnl, 4),
            pnl_pct=round(pnl / pos.margin * 100, 2),
            exit_reason=reason, bars_held=pos.bars_held,
        ))
        if reason in ("stop_loss", "liquidation"):
            self.cooldowns[sym] = self.cfg.cooldown_bars

    # ── main simulation ──────────────────────────────────────────────────

    def prepare_data(self, data_dir: str = "data/history/1h") -> dict:
        """Load market data and pre-compute reusable indicators."""
        if self.cfg.verbose:
            print("Loading data …")
        csvs = sorted(Path(data_dir).glob("*.csv"))
        if not csvs:
            if self.cfg.verbose:
                print(f"  ✗ no CSV files in {data_dir}")
            return {"error": "no data"}

        sym_data: Dict[str, dict] = {}
        btc_regime: Dict[str, bool] = {}       # BTC trend filter

        for fp in csvs:
            sym = fp.stem
            try:
                raw = pd.read_csv(fp)
            except Exception:
                continue
            if len(raw) < 220:                  # need EMA-200 warmup
                continue

            if sym == "BTCUSDT":
                df_btc = self._compute_regime(raw)
                df_btc = df_btc.dropna(subset=["ema_regime"]).reset_index(drop=True)
                for _, row in df_btc.iterrows():
                    btc_regime[row["da"]] = bool(row["regime_bull"])

            df = self._compute(raw)
            df = df.dropna(subset=["rsi", "ema_f", "ema_s", "atr"]).reset_index(drop=True)
            if df.empty:
                continue
            # store as numpy for speed
            sym_data[sym] = {
                "da":    df["da"].values,
                "cl":    df["cl"].values.astype(float),
                "hi":    df["hi"].values.astype(float),
                "lo":    df["lo"].values.astype(float),
                "atr":   df["atr"].values.astype(float),
                "rsi":   df["rsi"].values.astype(float),
                "vol_r": df["vol_r"].values.astype(float),
                "prev_hi": df["prev_hi"].values.astype(float),
                "cr": df["cr"].values.astype(float),
                "trend_up": df["trend_up"].values.astype(bool),
                "score": df["score"].values.astype(float),
                "n":     len(df),
            }

        n_sym = len(sym_data)
        if n_sym == 0:
            if self.cfg.verbose:
                print("  ✗ no symbols with enough data")
            return {"error": "insufficient data"}

        all_da = set()
        for d in sym_data.values():
            all_da.update(d["da"])
        timeline = sorted(all_da)
        return {
            "symbols": sym_data,
            "btc_regime": btc_regime,
            "timeline": timeline,
        }

    def run(self, data_dir: str = "data/history/1h") -> dict:
        """Load data, simulate bar-by-bar, return performance report."""
        prepared = self.prepare_data(data_dir)
        if "error" in prepared:
            return prepared
        return self.run_prepared(prepared)

    def run_prepared(self, prepared: dict) -> dict:
        """Run simulation using a pre-computed market snapshot."""
        if "error" in prepared:
            return prepared

        self._reset_state()
        sym_data = prepared["symbols"]
        btc_regime = prepared["btc_regime"]
        timeline = prepared["timeline"]
        timeline_index = pd.to_datetime(timeline)
        self._timeline_start = timeline_index[0]
        self._timeline_end = timeline_index[-1]
        if len(timeline_index) >= 2:
            step_seconds = timeline_index.to_series().diff().dropna().dt.total_seconds()
            if not step_seconds.empty:
                self._bar_seconds = float(step_seconds.median())

        enabled_symbols = {
            sym for sym in sym_data
            if self._is_symbol_enabled(sym)
        }
        n_sym = len(enabled_symbols)
        if n_sym == 0:
            if self.cfg.verbose:
                print("  ✗ no enabled symbols after filtering")
            return {"error": "no enabled symbols"}

        has_regime = len(btc_regime) > 0
        if self.cfg.verbose:
            print(f"  {n_sym} symbols loaded")
            print(f"  BTC regime filter: {'ON' if has_regime else 'OFF (no BTCUSDT data)'}")
            print(f"  period : {timeline[0]} → {timeline[-1]}")
            print(f"  bars   : {len(timeline):,}")
            print(f"  capital: {self.capital} USDT")
            print("-" * 60)

        # 3 — pointers
        ptrs = {s: 0 for s in enabled_symbols}

        # 4 — bar-by-bar simulation -------------------------------------------
        n_bars = len(timeline)
        for bi, t in enumerate(timeline):

            # advance pointers & gather active bars
            active: Dict[str, int] = {}
            for sym in enabled_symbols:
                d = sym_data[sym]
                p = ptrs[sym]
                while p < d["n"] and d["da"][p] < t:
                    p += 1
                if p < d["n"] and d["da"][p] == t:
                    active[sym] = p
                    ptrs[sym] = p + 1
                else:
                    ptrs[sym] = p

            # tick cooldowns
            for s in list(self.cooldowns):
                self.cooldowns[s] -= 1
                if self.cooldowns[s] <= 0:
                    del self.cooldowns[s]

            # ── exits ─────────────────────────────────────────────────────
            for sym in list(self.positions):
                if sym not in active:
                    continue
                idx = active[sym]
                d = sym_data[sym]
                pos = self.positions[sym]
                pos.bars_held += 1
                hi = d["hi"][idx]
                lo = d["lo"][idx]
                cl = d["cl"][idx]
                rsi = d["rsi"][idx]

                # trailing-stop update
                if hi > pos.highest_price:
                    pos.highest_price = hi
                    pft = (hi - pos.entry_price) / pos.entry_price
                    if pft >= self.cfg.trailing_act_pct:
                        new_ts = hi * (1 - self.cfg.trailing_dist_pct)
                        pos.trailing_stop = max(pos.trailing_stop, new_ts)

                if lo <= pos.stop_loss:
                    self._close(sym, pos.stop_loss, t, "stop_loss"); continue
                if pos.trailing_stop > pos.stop_loss and lo <= pos.trailing_stop:
                    self._close(sym, pos.trailing_stop, t, "trailing_stop"); continue
                if pos.bars_held >= self.cfg.max_hold_bars:
                    self._close(sym, cl, t, "max_hold"); continue
                if rsi > self.cfg.rsi_exit_max:
                    self._close(sym, cl, t, "rsi_exhaustion"); continue

            # ── equity snapshot (before entries) ─────────────────────────
            equity = self.capital + self.locked_profit
            for sym, pos in self.positions.items():
                if sym in active:
                    cl_v = sym_data[sym]["cl"][active[sym]]
                else:
                    cl_v = pos.entry_price
                unrealised = pos.notional * (
                    (cl_v - pos.entry_price) / pos.entry_price
                )
                equity += pos.margin + unrealised
            self.peak_equity = max(self.peak_equity, equity)
            dd = (self.peak_equity - equity) / self.peak_equity if self.peak_equity else 0
            self.max_dd = max(self.max_dd, dd)

            # ── progressive profit locking ────────────────────────────────
            lock_threshold = self.lock_base * self.cfg.profit_lock_mult
            if equity > lock_threshold:
                excess = equity - self.lock_base
                to_lock = excess * self.cfg.profit_lock_ratio
                self.locked_profit += to_lock
                self.capital -= to_lock
                self.lock_base = equity - to_lock  # raise base for next lock
                self.peak_equity = equity - to_lock

            # ── portfolio equity trailing stop ────────────────────────────
            # Resume when BTC regime turns bullish (not fixed timer)
            if self.paused:
                btc_bull = btc_regime.get(t, False) if has_regime else True
                if btc_bull and len(self.positions) == 0:
                    self.paused = False
                    self.peak_equity = equity  # reset peak on resume

            if not self.paused and dd >= self.cfg.equity_trail_pct and len(self.positions) > 0:
                for sym in list(self.positions):
                    if sym in active:
                        cl_v = sym_data[sym]["cl"][active[sym]]
                    else:
                        cl_v = self.positions[sym].entry_price
                    self._close(sym, cl_v, t, "equity_stop")
                self.paused = True

            # ── entries ───────────────────────────────────────────────────
            allow_entry = (
                not self.paused
                and len(self.positions) < self.cfg.max_positions
                and self.capital >= self.cfg.capital_floor
            )
            # BTC regime check: only open in BTC uptrend (or when no data)
            if allow_entry and has_regime:
                allow_entry = btc_regime.get(t, False)

            if allow_entry:
                cands = []
                for sym, idx in active.items():
                    if sym in self.positions or sym in self.cooldowns:
                        continue
                    d = sym_data[sym]
                    if self._entry_signal(d, idx):
                        cands.append((sym, idx, d["score"][idx]))
                cands.sort(key=lambda x: x[2], reverse=True)
                slots = self.cfg.max_positions - len(self.positions)
                for sym, idx, sc in cands[:slots]:
                    d = sym_data[sym]
                    self._open(sym, d["cl"][idx], d["atr"][idx], sc, t)
                    if self.capital < self.cfg.capital_floor:
                        break

            # ── record equity curve ───────────────────────────────────────
            self._equity_points.append(float(equity))
            if bi % 100 == 0:
                self.equity_curve.append({"da": t, "equity": round(equity, 2)})
            if self.cfg.verbose and bi % 5000 == 0 and bi:
                flag = " [PAUSED]" if self.paused else ""
                lk = f" locked={self.locked_profit:.0f}" if self.locked_profit else ""
                print(f"  bar {bi:>8,}/{n_bars:,}  "
                      f"equity={equity:>10.2f}  trades={len(self.trades)}{flag}{lk}")

        # 5 — close remaining positions ----------------------------------------
        for sym in list(self.positions):
            d = sym_data[sym]
            self._close(sym, d["cl"][d["n"] - 1], d["da"][d["n"] - 1], "end_of_test")

        final_equity = float(self.capital + self.locked_profit)
        if not self._equity_points or abs(self._equity_points[-1] - final_equity) > 1e-9:
            self._equity_points.append(final_equity)

        return self._report()

    # ── report ────────────────────────────────────────────────────────────

    def _report(self) -> dict:
        if not self.trades:
            return {"error": "no trades"}

        wins   = [t for t in self.trades if t.pnl > 0]
        losses = [t for t in self.trades if t.pnl <= 0]

        g_win  = sum(t.pnl for t in wins)  if wins   else 0
        g_loss = sum(t.pnl for t in losses) if losses else 0
        pf = abs(g_win / g_loss) if g_loss else float("inf")

        # Use actual capital change for accuracy (include locked profit)
        total_equity = self.capital + self.locked_profit
        actual_pnl = total_equity - self.cfg.initial_capital
        actual_return = actual_pnl / self.cfg.initial_capital * 100
        period_stats = self._compute_period_stats(self.cfg.initial_capital, total_equity)

        reasons = {}
        for t in self.trades:
            reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1

        lev_d = {}
        for t in self.trades:
            k = f"{t.leverage}x"
            lev_d[k] = lev_d.get(k, 0) + 1

        sym_pnl: Dict[str, float] = {}
        for t in self.trades:
            sym_pnl[t.symbol] = sym_pnl.get(t.symbol, 0) + t.pnl
        top = sorted(sym_pnl.items(), key=lambda x: x[1], reverse=True)[:10]
        bottom = sorted(sym_pnl.items(), key=lambda x: x[1])[:5]

        return {
            "initial_capital": self.cfg.initial_capital,
            "final_capital": round(total_equity, 2),
            "locked_profit": round(self.locked_profit, 2),
            "trading_capital": round(self.capital, 2),
            "total_pnl": round(actual_pnl, 2),
            "return_pct": round(actual_return, 2),
            "annualized_return_pct": period_stats["annualized_return_pct"],
            "sharpe_ratio": period_stats["sharpe_ratio"],
            "calmar_ratio": period_stats["calmar_ratio"],
            "total_trades": len(self.trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(self.trades) * 100, 2),
            "avg_win": round(np.mean([t.pnl for t in wins]), 2) if wins else 0,
            "avg_loss": round(np.mean([t.pnl for t in losses]), 2) if losses else 0,
            "profit_factor": round(pf, 2) if pf != float("inf") else "∞",
            "max_drawdown_pct": round(self.max_dd * 100, 2),
            "avg_hold_bars": round(np.mean([t.bars_held for t in self.trades]), 1),
            "exit_reasons": reasons,
            "leverage_dist": lev_d,
            "top_symbols_pnl": {s: round(p, 2) for s, p in top},
            "worst_symbols_pnl": {s: round(p, 2) for s, p in bottom},
        }

    # ── persist results ───────────────────────────────────────────────────

    def save_results(self, out_dir: str = "data", prefix: str = "backtest"):
        os.makedirs(out_dir, exist_ok=True)
        if self.trades:
            df = pd.DataFrame([vars(t) for t in self.trades])
            p = os.path.join(out_dir, f"{prefix}_trades.csv")
            df.to_csv(p, index=False)
            print(f"  Trades → {p}  ({len(self.trades)} rows)")
        if self.equity_curve:
            df = pd.DataFrame(self.equity_curve)
            p = os.path.join(out_dir, f"{prefix}_equity.csv")
            df.to_csv(p, index=False)
            print(f"  Equity → {p}  ({len(self.equity_curve)} points)")
