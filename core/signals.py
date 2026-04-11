"""
Signals — technical indicator computation and signal generation
Refactored from Codex analyze_kline.py with enhanced logic.
"""
import pandas as pd
import ta
from dataclasses import dataclass
from typing import Optional

from core.exchange import get_exchange
from config.settings import SETTINGS
from utils.logger import logger, log_signal


@dataclass
class Signal:
    symbol: str
    direction: str          # 'LONG', 'SHORT', 'NEUTRAL'
    setup: str              # 'A', 'B', 'C', 'D' or 'NONE'
    strength: float         # 0.0 ~ 1.0
    entry_price: float
    rsi: float
    ema_fast: float
    ema_slow: float
    volume_ratio: float     # current vol / avg vol
    reasons: list


def _ema(series: pd.Series, length: int) -> pd.Series:
    """Support both legacy `n=` and newer `window=` ta APIs."""
    try:
        indicator = ta.trend.EMAIndicator(close=series, window=length)
    except TypeError:
        indicator = ta.trend.EMAIndicator(close=series, n=length)
    return indicator.ema_indicator()


def _rsi(series: pd.Series, length: int) -> pd.Series:
    """Support both legacy `n=` and newer `window=` ta APIs."""
    try:
        indicator = ta.momentum.RSIIndicator(close=series, window=length)
    except TypeError:
        indicator = ta.momentum.RSIIndicator(close=series, n=length)
    return indicator.rsi()


def fetch_klines(symbol: str, timeframe: str = '5m', limit: int = 100) -> Optional[pd.DataFrame]:
    """Fetch OHLCV data and return as DataFrame."""
    exchange = get_exchange()
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        logger.error(f"Failed to fetch klines for {symbol}: {e}")
        return None


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all technical indicators on OHLCV DataFrame."""
    df = df.copy()
    df['ema_9'] = _ema(df['close'], 9)
    df['ema_21'] = _ema(df['close'], 21)
    df['rsi_14'] = _rsi(df['close'], 14)
    df['vol_ma_20'] = df['volume'].rolling(window=20).mean()
    df['volume_ratio'] = (
        df['volume'] / df['vol_ma_20'].replace(0, pd.NA)
    ).replace([float('inf'), float('-inf')], pd.NA)

    # Upper shadow ratio: (high - max(open,close)) / (high - low)
    body_top = df[['open', 'close']].max(axis=1)
    candle_range = (df['high'] - df['low']).replace(0, pd.NA)
    df['upper_shadow_ratio'] = ((df['high'] - body_top) / candle_range).fillna(0)

    # Prior 20-bar range for breakout detection (exclude the current candle).
    df['prior_high_20'] = df['high'].rolling(window=20).max().shift(1)
    df['prior_low_20'] = df['low'].rolling(window=20).min().shift(1)

    return df


def analyze(symbol: str, timeframe: str = '5m', limit: int = 100) -> Signal:
    """
    Full signal analysis for a single symbol.
    Returns a Signal object with direction, setup type, and strength.
    """
    df = fetch_klines(symbol, timeframe, limit)
    if df is None or len(df) < 50:
        return Signal(symbol, 'NEUTRAL', 'NONE', 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, ['insufficient data'])

    df = compute_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    rsi = latest['rsi_14']
    ema_fast = latest['ema_9']
    ema_slow = latest['ema_21']
    vol_ratio = latest['volume_ratio'] if pd.notna(latest['volume_ratio']) else 0
    price = latest['close']
    breakout_level = latest['prior_high_20']
    prev_breakout_level = prev['prior_high_20']

    if pd.isna(rsi) or pd.isna(ema_fast) or pd.isna(ema_slow):
        return Signal(symbol, 'NEUTRAL', 'NONE', 0.0, float(price), 0.0, 0.0, 0.0, 0.0,
                      ['indicator warmup incomplete'])

    reasons = []
    direction = 'NEUTRAL'
    setup = 'NONE'
    strength = 0.0

    cfg_long = SETTINGS.long_entry
    cfg_short = SETTINGS.short_entry

    # --- Setup A: Long Breakout Continuation ---
    if pd.notna(breakout_level) and price > breakout_level * 0.998:
        if vol_ratio >= cfg_long.volume_multiplier:
            if rsi > cfg_long.rsi_breakout:
                direction = 'LONG'
                setup = 'A'
                strength = min(1.0, 0.5 + (vol_ratio / 10) + (rsi - 60) / 100)
                reasons.append(
                    f"Breakout above prior 20-bar high {breakout_level:.6f}, "
                    f"vol_ratio={vol_ratio:.1f}, RSI={rsi:.1f}"
                )

    # --- Setup B: Long First Pullback (from Codex analyze_kline.py) ---
    if direction == 'NEUTRAL' and ema_fast > ema_slow:
        if price <= ema_fast and rsi < 50:
            direction = 'LONG'
            setup = 'B'
            strength = min(1.0, 0.4 + (ema_fast - ema_slow) / ema_slow * 10)
            reasons.append(f"Pullback to EMA9 in uptrend, RSI cooling={rsi:.1f}")

    # --- Setup C: Short Failed Breakout ---
    if direction == 'NEUTRAL':
        if pd.notna(prev_breakout_level) and prev['high'] >= prev_breakout_level * 0.998:
            if price < prev['high'] and price < latest['open']:
                if vol_ratio >= 2.0:
                    direction = 'SHORT'
                    setup = 'C'
                    strength = min(1.0, 0.5 + vol_ratio / 10)
                    reasons.append(
                        f"Failed breakout from prior 20-bar high {prev_breakout_level:.6f}, "
                        f"vol_ratio={vol_ratio:.1f}"
                    )

    # --- Setup D: Short Parabolic Exhaustion (from Codex analyze_kline.py) ---
    if direction == 'NEUTRAL':
        if vol_ratio >= cfg_long.volume_multiplier:
            if price < latest['open']:  # bearish candle with huge volume
                direction = 'SHORT'
                setup = 'D'
                strength = min(1.0, 0.4 + vol_ratio / 10)
                reasons.append(f"High-volume bearish candle, possible exhaustion")
            elif rsi > cfg_short.rsi_overbought:
                direction = 'SHORT'
                setup = 'D'
                strength = min(1.0, 0.4 + (rsi - 80) / 40)
                reasons.append(f"RSI extreme overbought={rsi:.1f} with volume spike")

    signal = Signal(
        symbol=symbol,
        direction=direction,
        setup=setup,
        strength=round(strength, 3),
        entry_price=round(price, 8),
        rsi=round(rsi, 2),
        ema_fast=round(ema_fast, 8),
        ema_slow=round(ema_slow, 8),
        volume_ratio=round(vol_ratio, 2),
        reasons=reasons,
    )

    if direction != 'NEUTRAL':
        log_signal(symbol, f"{direction}/{setup}", strength,
                   rsi=rsi, vol_ratio=vol_ratio, price=price)

    return signal


def analyze_batch(symbols: list, timeframe: str = '5m') -> list:
    """Analyze multiple symbols and return only actionable signals."""
    signals = []
    for sym in symbols:
        sig = analyze(sym, timeframe)
        if sig.direction != 'NEUTRAL':
            signals.append(sig)
    signals.sort(key=lambda s: s.strength, reverse=True)
    return signals
