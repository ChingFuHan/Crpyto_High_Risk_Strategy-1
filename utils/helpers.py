"""
Helper utilities
"""
from datetime import datetime, timezone


def ts_now() -> datetime:
    return datetime.now(timezone.utc)


def fmt_usdt(amount: float) -> str:
    return f"{amount:,.2f} USDT"


def pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def ccxt_symbol(base: str, quote: str = 'USDT') -> str:
    """Convert to ccxt perpetual symbol format: BTC/USDT:USDT"""
    base = base.upper().replace('USDT', '')
    return f"{base}/{quote}:{quote}"
