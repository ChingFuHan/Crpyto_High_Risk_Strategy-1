"""
Paper Trader — virtual trading simulator with improved accuracy
Evolved from Codex paper_trade.py with proper fee/liquidation math.
"""
import json
import os
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from pathlib import Path

from config.settings import SETTINGS
from utils.logger import logger, log_trade


DATA_DIR = Path(__file__).resolve().parent.parent / 'data'
PORTFOLIO_FILE = DATA_DIR / 'portfolio.json'


@dataclass
class PaperPosition:
    symbol: str
    side: str           # 'LONG' or 'SHORT'
    entry_price: float
    margin: float
    leverage: int
    qty: float
    liquidation_price: float
    setup: str = ''


@dataclass
class PaperPortfolio:
    balance: float = 500.0
    positions: List[dict] = field(default_factory=list)


class PaperTrader:
    def __init__(self, initial_balance: float = 500.0):
        DATA_DIR.mkdir(exist_ok=True)
        self.portfolio = self._load()
        if self.portfolio is None:
            self.portfolio = PaperPortfolio(balance=initial_balance)
            self._save()

    def _load(self) -> Optional[PaperPortfolio]:
        if PORTFOLIO_FILE.exists():
            try:
                with open(PORTFOLIO_FILE, 'r') as f:
                    data = json.load(f)
                return PaperPortfolio(
                    balance=data.get('balance', 500.0),
                    positions=data.get('positions', []),
                )
            except Exception:
                return None
        return None

    def _save(self):
        with open(PORTFOLIO_FILE, 'w') as f:
            json.dump({
                'balance': self.portfolio.balance,
                'positions': self.portfolio.positions,
            }, f, indent=2)

    @property
    def balance(self) -> float:
        return self.portfolio.balance

    def calc_liquidation_price(self, entry: float, leverage: int,
                                side: str) -> float:
        """
        Improved liquidation price using maintenance margin rate.
        Liq occurs when unrealized loss = initial margin - maintenance margin.
        """
        mm_rate = SETTINGS.maintenance_margin_rate
        if side == 'LONG':
            return entry * (1 - (1 / leverage) + mm_rate)
        else:
            return entry * (1 + (1 / leverage) - mm_rate)

    def open_position(self, symbol: str, side: str, price: float,
                      amount_usd: float, leverage: int,
                      setup: str = '') -> bool:
        """Open a paper position with fee deduction."""
        if leverage not in [1, 3, 5]:
            logger.warning(f"Invalid leverage {leverage}x, must be 1/3/5")
            return False

        if amount_usd > self.portfolio.balance:
            logger.warning(f"Insufficient balance: {self.portfolio.balance:.2f}")
            return False

        # Deduct trading fee from margin
        fee = amount_usd * leverage * SETTINGS.trading_fee_rate
        margin = amount_usd
        position_size = margin * leverage
        qty = position_size / price
        liq_price = self.calc_liquidation_price(price, leverage, side)

        pos = {
            'symbol': symbol,
            'side': side,
            'entry_price': price,
            'margin': margin,
            'leverage': leverage,
            'qty': qty,
            'liquidation_price': round(liq_price, 8),
            'fee_paid': round(fee, 4),
            'setup': setup,
        }

        self.portfolio.balance -= margin
        self.portfolio.positions.append(pos)
        self._save()

        log_trade('PAPER_OPEN', symbol, side=side, leverage=f"{leverage}x",
                  margin=f"{margin:.2f}", qty=f"{qty:.6f}",
                  entry=f"{price:.6f}", liq=f"{liq_price:.6f}", fee=f"{fee:.4f}")
        return True

    def close_position(self, symbol: str, current_price: float) -> Optional[float]:
        """Close a paper position and return PnL."""
        for idx, pos in enumerate(self.portfolio.positions):
            if pos['symbol'] == symbol:
                side = pos['side']
                entry = pos['entry_price']
                qty = pos['qty']
                margin = pos['margin']

                if side == 'LONG':
                    pnl = (current_price - entry) * qty
                else:
                    pnl = (entry - current_price) * qty

                # Deduct closing fee
                close_fee = current_price * qty * SETTINGS.trading_fee_rate
                pnl -= close_fee
                pnl -= pos.get('fee_paid', 0)  # also subtract open fee

                self.portfolio.balance += (margin + pnl)
                del self.portfolio.positions[idx]
                self._save()

                log_trade('PAPER_CLOSE', symbol, side=side,
                          entry=f"{entry:.6f}", exit=f"{current_price:.6f}",
                          pnl=f"{pnl:.2f}", balance=f"{self.portfolio.balance:.2f}")
                return pnl

        logger.warning(f"No position found for {symbol}")
        return None

    def check_liquidations(self, prices: dict):
        """Check if any positions hit liquidation price."""
        liquidated = []
        for pos in self.portfolio.positions[:]:
            price = prices.get(pos['symbol'])
            if price is None:
                continue

            if pos['side'] == 'LONG' and price <= pos['liquidation_price']:
                liquidated.append(pos)
            elif pos['side'] == 'SHORT' and price >= pos['liquidation_price']:
                liquidated.append(pos)

        for pos in liquidated:
            self.portfolio.positions.remove(pos)
            log_trade('PAPER_LIQUIDATED', pos['symbol'],
                      side=pos['side'], margin_lost=f"{pos['margin']:.2f}")

        if liquidated:
            self._save()

        return liquidated

    def get_status(self) -> dict:
        total_margin = sum(p['margin'] for p in self.portfolio.positions)
        return {
            'balance': round(self.portfolio.balance, 2),
            'total_margin_locked': round(total_margin, 2),
            'equity': round(self.portfolio.balance + total_margin, 2),
            'positions': len(self.portfolio.positions),
            'position_details': self.portfolio.positions,
        }

    def print_status(self):
        status = self.get_status()
        print(f"\n{'='*50}")
        print(f"  Paper Trading Account")
        print(f"{'='*50}")
        print(f"  Balance:       {status['balance']:>10.2f} USDT")
        print(f"  Margin Locked: {status['total_margin_locked']:>10.2f} USDT")
        print(f"  Equity:        {status['equity']:>10.2f} USDT")
        print(f"  Positions:     {status['positions']}")
        for p in status['position_details']:
            print(f"    {p['side']:5} {p['symbol']} | {p['leverage']}x "
                  f"| margin={p['margin']:.2f} | entry={p['entry_price']:.6f}")
        print(f"{'='*50}\n")
