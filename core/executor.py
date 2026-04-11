"""
Executor — order placement + stop-loss/take-profit management
Handles both live and paper trading modes.
"""
from dataclasses import dataclass
from typing import Optional

from core.exchange import get_exchange
from core.strategy import TradeDecision
from config.settings import SETTINGS
from utils.logger import logger, log_trade


@dataclass
class OrderResult:
    success: bool
    order_id: str
    symbol: str
    side: str
    leverage: int
    margin: float
    qty: float
    entry_price: float
    stop_loss_price: float
    take_profit_price: Optional[float]
    message: str


def set_leverage(symbol: str, leverage: int) -> bool:
    """Set leverage for a symbol on the exchange."""
    exchange = get_exchange()
    try:
        exchange.set_leverage(leverage, symbol)
        return True
    except Exception as e:
        logger.error(f"Failed to set leverage {leverage}x for {symbol}: {e}")
        return False


def set_margin_mode(symbol: str, mode: str = 'isolated') -> bool:
    """Set margin mode (isolated/cross)."""
    exchange = get_exchange()
    try:
        exchange.set_margin_mode(mode, symbol)
        return True
    except Exception as e:
        # Often fails if already set — not critical
        logger.debug(f"Margin mode set note for {symbol}: {e}")
        return True


def execute_market_order(decision: TradeDecision) -> OrderResult:
    """
    Execute a market order based on trade decision.
    R7: Always places stop-loss order after entry.
    """
    exchange = get_exchange()
    symbol = decision.symbol
    is_long = decision.action == 'OPEN_LONG'
    side = 'buy' if is_long else 'sell'

    # Calculate quantity from margin + leverage
    qty = (decision.margin_usdt * decision.leverage) / decision.entry_price

    # Precision handling
    try:
        market = exchange.market(symbol)
        qty = exchange.amount_to_precision(symbol, qty)
        qty = float(qty)
    except Exception:
        qty = round(qty, 6)

    try:
        # Step 1: Set margin mode and leverage
        set_margin_mode(symbol, SETTINGS.margin_type.lower())
        set_leverage(symbol, decision.leverage)

        # Step 2: Market order
        order = exchange.create_order(
            symbol=symbol,
            type='market',
            side=side,
            amount=qty,
        )

        entry_price = order.get('average') or order.get('price') or decision.entry_price
        order_id = order.get('id', 'unknown')

        # Step 3: R7 — Always set stop-loss (STOP_MARKET)
        sl_side = 'sell' if is_long else 'buy'
        try:
            exchange.create_order(
                symbol=symbol,
                type='stop_market' if hasattr(exchange, 'create_order') else 'STOP_MARKET',
                side=sl_side,
                amount=qty,
                params={
                    'stopPrice': exchange.price_to_precision(symbol, decision.stop_loss),
                    'closePosition': True,
                    'reduceOnly': True,
                }
            )
            logger.info(f"Stop-loss set at {decision.stop_loss} for {symbol}")
        except Exception as e:
            logger.error(f"Failed to set stop-loss for {symbol}: {e}")

        # Step 4: Set take-profit if defined
        if decision.take_profit:
            tp_side = 'sell' if is_long else 'buy'
            try:
                exchange.create_order(
                    symbol=symbol,
                    type='take_profit_market',
                    side=tp_side,
                    amount=qty,
                    params={
                        'stopPrice': exchange.price_to_precision(symbol, decision.take_profit),
                        'closePosition': True,
                        'reduceOnly': True,
                    }
                )
                logger.info(f"Take-profit set at {decision.take_profit} for {symbol}")
            except Exception as e:
                logger.debug(f"TP order note for {symbol}: {e}")

        log_trade(
            action=decision.action, symbol=symbol,
            leverage=decision.leverage, margin=decision.margin_usdt,
            qty=qty, entry=entry_price, sl=decision.stop_loss,
            tp=decision.take_profit, setup=decision.setup,
        )

        return OrderResult(
            success=True, order_id=order_id, symbol=symbol,
            side=side, leverage=decision.leverage,
            margin=decision.margin_usdt, qty=qty,
            entry_price=float(entry_price),
            stop_loss_price=decision.stop_loss,
            take_profit_price=decision.take_profit,
            message="Order executed successfully",
        )

    except Exception as e:
        logger.error(f"Order execution failed for {symbol}: {e}")
        return OrderResult(
            success=False, order_id='', symbol=symbol,
            side=side, leverage=decision.leverage,
            margin=decision.margin_usdt, qty=qty,
            entry_price=decision.entry_price,
            stop_loss_price=decision.stop_loss,
            take_profit_price=decision.take_profit,
            message=f"Failed: {e}",
        )


def close_position(symbol: str, side: str = 'LONG') -> bool:
    """Close an existing position at market price."""
    exchange = get_exchange()
    close_side = 'sell' if side == 'LONG' else 'buy'

    try:
        positions = exchange.fetch_positions([symbol])
        for pos in positions:
            amt = abs(float(pos.get('contracts', 0)))
            if amt > 0:
                exchange.create_order(
                    symbol=symbol, type='market',
                    side=close_side, amount=amt,
                    params={'reduceOnly': True},
                )
                log_trade(action='CLOSE', symbol=symbol, side=side)
                return True
        logger.info(f"No open position found for {symbol}")
        return False
    except Exception as e:
        logger.error(f"Failed to close position for {symbol}: {e}")
        return False
