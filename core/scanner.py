"""
Scanner — full-market volume/price anomaly detector
Refactored from Codex scan_pump.py into a modular engine.
"""
import pandas as pd
from typing import List, Dict, Optional

from core.exchange import get_exchange
from config.settings import SETTINGS
from config.pairs_whitelist import BLACKLIST, WHITELIST, QUOTE_CURRENCY, MIN_24H_VOLUME_USDT
from utils.logger import logger


def fetch_all_tickers() -> Dict:
    """Fetch 24h tickers for all perpetual contracts."""
    exchange = get_exchange()
    return exchange.fetch_tickers()


def filter_tradable_pairs(tickers: Dict) -> pd.DataFrame:
    """
    Filter tickers to tradable USDT perpetual pairs.
    Applies volume threshold, blacklist, and whitelist filters.
    """
    rows = []
    suffix = f':{QUOTE_CURRENCY}'

    for symbol, ticker in tickers.items():
        if not symbol.endswith(suffix):
            continue

        # Blacklist check (convert ccxt symbol to plain pair)
        plain = symbol.replace('/', '').split(':')[0]
        if plain in BLACKLIST:
            continue

        quote_vol = ticker.get('quoteVolume') or 0
        if quote_vol < MIN_24H_VOLUME_USDT:
            continue

        # If whitelist is set, only include those
        if WHITELIST and plain not in WHITELIST:
            continue

        rows.append({
            'symbol': symbol,
            'last': ticker.get('last', 0),
            'change_pct': ticker.get('percentage', 0),
            'volume_usdt': quote_vol,
            'high': ticker.get('high', 0),
            'low': ticker.get('low', 0),
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def scan_top_gainers(top_n: Optional[int] = None) -> pd.DataFrame:
    """
    Scan the full market and return top N gainers by 24h change.
    This is the primary entry point — replaces Codex scan_pump.py.
    """
    if top_n is None:
        top_n = SETTINGS.scanner.top_n

    logger.info("Scanning full market for top gainers...")
    tickers = fetch_all_tickers()
    df = filter_tradable_pairs(tickers)

    if df.empty:
        logger.warning("No tradable pairs found after filtering")
        return df

    df = df.sort_values('change_pct', ascending=False).head(top_n).reset_index(drop=True)
    logger.info(f"Found {len(df)} top gainers")
    return df


def scan_top_losers(top_n: Optional[int] = None) -> pd.DataFrame:
    """Scan for top losers — potential short candidates."""
    if top_n is None:
        top_n = SETTINGS.scanner.top_n

    logger.info("Scanning full market for top losers...")
    tickers = fetch_all_tickers()
    df = filter_tradable_pairs(tickers)

    if df.empty:
        return df

    df = df.sort_values('change_pct', ascending=True).head(top_n).reset_index(drop=True)
    logger.info(f"Found {len(df)} top losers")
    return df


def scan_volume_anomalies(threshold_multiplier: float = 3.0) -> pd.DataFrame:
    """
    Find pairs with abnormal 24h volume relative to typical levels.
    Note: without historical volume baseline, uses absolute thresholds.
    """
    tickers = fetch_all_tickers()
    df = filter_tradable_pairs(tickers)

    if df.empty:
        return df

    # Pairs where volume is significantly above the minimum threshold
    high_vol = df[df['volume_usdt'] > MIN_24H_VOLUME_USDT * threshold_multiplier]
    return high_vol.sort_values('volume_usdt', ascending=False).reset_index(drop=True)
