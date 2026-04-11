"""
Strategy — trade decision engine
Integrates signals + risk check to produce actionable trade decisions.
Implements Setup A/B/C/D from the strategy framework.
"""
from dataclasses import dataclass
from typing import Optional

from core.signals import Signal
from config.settings import SETTINGS
from utils.logger import logger


@dataclass
class TradeDecision:
    symbol: str
    action: str             # 'OPEN_LONG', 'OPEN_SHORT', 'SKIP'
    setup: str              # A/B/C/D
    leverage: int
    margin_usdt: float      # how much margin to commit
    entry_price: float
    stop_loss: float
    take_profit: Optional[float]
    strength: float
    reasons: list


def decide_leverage(signal: Signal) -> int:
    """Dynamic leverage based on signal strength."""
    cfg = SETTINGS.leverage
    if signal.strength >= 0.8:
        return cfg.high_signal
    elif signal.strength >= 0.5:
        return cfg.medium_signal
    else:
        return cfg.low_signal


def calc_stop_loss(signal: Signal, leverage: int) -> float:
    """Calculate stop-loss price based on direction and leverage."""
    if signal.direction == 'LONG':
        sl_pct = SETTINGS.long_entry.sl_by_leverage.get(leverage, 0.08)
        return signal.entry_price * (1 - sl_pct)
    else:
        sl_pct = SETTINGS.short_entry.sl_by_leverage.get(leverage, 0.05)
        return signal.entry_price * (1 + sl_pct)


def calc_take_profit(signal: Signal) -> Optional[float]:
    """Calculate first take-profit level."""
    if signal.direction == 'LONG':
        first_tp = SETTINGS.long_entry.tp_levels[0]
        return signal.entry_price * (1 + first_tp['target_pct'])
    else:
        return signal.entry_price * (1 - SETTINGS.short_entry.tp_target_pct)


def calc_margin(balance: float, leverage: int) -> float:
    """Position sizing: allocate margin based on risk config."""
    max_size = balance * SETTINGS.risk.max_position_size
    return round(max_size, 2)


def evaluate(signal: Signal, balance: float) -> TradeDecision:
    """
    Evaluate a signal and produce a trade decision.
    This is the main entry point for the strategy engine.
    """
    if signal.direction == 'NEUTRAL':
        return TradeDecision(
            symbol=signal.symbol, action='SKIP', setup='NONE',
            leverage=1, margin_usdt=0, entry_price=signal.entry_price,
            stop_loss=0, take_profit=None, strength=0, reasons=['no signal'],
        )

    # Short positions limited to lower leverage
    leverage = decide_leverage(signal)
    if signal.direction == 'SHORT':
        leverage = min(leverage, SETTINGS.leverage.short_max)

    stop_loss = calc_stop_loss(signal, leverage)
    take_profit = calc_take_profit(signal)
    margin = calc_margin(balance, leverage)

    action = 'OPEN_LONG' if signal.direction == 'LONG' else 'OPEN_SHORT'

    decision = TradeDecision(
        symbol=signal.symbol,
        action=action,
        setup=signal.setup,
        leverage=leverage,
        margin_usdt=margin,
        entry_price=signal.entry_price,
        stop_loss=round(stop_loss, 8),
        take_profit=round(take_profit, 8) if take_profit else None,
        strength=signal.strength,
        reasons=signal.reasons,
    )

    logger.info(
        f"[STRATEGY] {action} {signal.symbol} | setup={signal.setup} "
        f"lev={leverage}x | margin={margin} | SL={stop_loss:.6f} | TP={take_profit}"
    )
    return decision
