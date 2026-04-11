"""
Risk Manager — enforces hard risk rules R1-R8
This is the safety layer that prevents account destruction.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List

from config.settings import SETTINGS
from utils.logger import logger, log_risk


@dataclass
class PositionInfo:
    symbol: str
    side: str
    margin: float
    leverage: int
    entry_time: datetime


@dataclass
class RiskState:
    """Tracks runtime risk state."""
    balance: float = 500.0
    daily_start_balance: float = 500.0
    daily_loss: float = 0.0
    consecutive_losses: int = 0
    cooldown_until: datetime | None = None
    open_positions: List[PositionInfo] = field(default_factory=list)
    survival_mode: bool = False
    last_daily_reset: datetime = field(default_factory=datetime.utcnow)


class RiskManager:
    def __init__(self, initial_balance: float = 500.0):
        self.cfg = SETTINGS.risk
        self.state = RiskState(
            balance=initial_balance,
            daily_start_balance=initial_balance,
        )
        self._check_survival_mode()

    def update_balance(self, new_balance: float):
        self.state.balance = new_balance
        self._check_survival_mode()
        self._check_profit_take()

    def _check_survival_mode(self):
        """R5: Below 200U -> 1x only; above 400U -> resume normal."""
        if self.state.balance <= self.cfg.survival_threshold:
            if not self.state.survival_mode:
                self.state.survival_mode = True
                log_risk("SURVIVAL_MODE_ON", balance=self.state.balance)
        elif self.state.balance >= self.cfg.recovery_threshold:
            if self.state.survival_mode:
                self.state.survival_mode = False
                log_risk("SURVIVAL_MODE_OFF", balance=self.state.balance)

    def _check_profit_take(self):
        """R6: Above 2000U -> signal to take 50% profit."""
        if self.state.balance >= self.cfg.profit_take_threshold:
            log_risk("PROFIT_TAKE_SIGNAL",
                     balance=self.state.balance,
                     withdraw=self.state.balance * self.cfg.profit_take_ratio)

    def can_open_position(self, symbol: str, side: str, margin: float,
                          leverage: int) -> tuple[bool, str]:
        """
        Check all risk rules before opening a position.
        Returns (allowed, reason).
        """
        now = datetime.utcnow()

        # Daily reset
        if (now - self.state.last_daily_reset).total_seconds() > 86400:
            self.state.daily_loss = 0.0
            self.state.daily_start_balance = self.state.balance
            self.state.last_daily_reset = now

        # R4: Cooldown check
        if self.state.cooldown_until and now < self.state.cooldown_until:
            remaining = (self.state.cooldown_until - now).total_seconds() / 60
            return False, f"R4: Cooldown active, {remaining:.0f} min remaining"

        # R2: Max positions
        if len(self.state.open_positions) >= self.cfg.max_positions:
            return False, f"R2: Max {self.cfg.max_positions} positions already open"

        # R5: Survival mode leverage check
        if self.state.survival_mode and leverage > self.cfg.survival_leverage:
            return False, f"R5: Survival mode — only {self.cfg.survival_leverage}x allowed"

        # Max 5x positions
        n_5x = sum(1 for p in self.state.open_positions if p.leverage >= 5)
        if leverage >= 5 and n_5x >= self.cfg.max_5x_positions:
            return False, f"Max {self.cfg.max_5x_positions} concurrent 5x position(s)"

        # R1: Single trade max loss check
        max_loss_amount = self.state.balance * self.cfg.max_loss_per_trade
        potential_loss = margin  # worst case = lose entire margin
        if potential_loss > max_loss_amount:
            return False, f"R1: Margin {margin:.2f} exceeds max loss {max_loss_amount:.2f}"

        # Position size cap
        if margin > self.state.balance * self.cfg.max_position_size:
            return False, f"Position too large: {margin:.2f} > {self.state.balance * self.cfg.max_position_size:.2f}"

        # Balance check
        if margin > self.state.balance:
            return False, f"Insufficient balance: {self.state.balance:.2f}"

        # R3: Daily loss limit
        if self.state.daily_loss >= self.state.daily_start_balance * self.cfg.max_daily_loss:
            return False, f"R3: Daily loss limit reached ({self.state.daily_loss:.2f})"

        return True, "OK"

    def on_position_opened(self, symbol: str, side: str, margin: float, leverage: int):
        """Register a new position."""
        self.state.open_positions.append(
            PositionInfo(symbol=symbol, side=side, margin=margin,
                         leverage=leverage, entry_time=datetime.utcnow())
        )
        self.state.balance -= margin
        logger.info(f"[RISK] Position opened: {side} {symbol} margin={margin} lev={leverage}x")

    def on_position_closed(self, symbol: str, pnl: float):
        """Handle position closure."""
        closed_position = next(
            (p for p in self.state.open_positions if p.symbol == symbol),
            None,
        )
        self.state.open_positions = [
            p for p in self.state.open_positions if p.symbol != symbol
        ]

        if closed_position is None:
            logger.warning(f"[RISK] Closed position not tracked: {symbol}")
        else:
            self.state.balance += closed_position.margin + pnl

        if pnl < 0:
            self.state.daily_loss += abs(pnl)
            self.state.consecutive_losses += 1
            log_risk("LOSS", symbol=symbol, pnl=f"{pnl:.2f}",
                     consecutive=self.state.consecutive_losses)

            # R4: Consecutive loss cooldown
            if self.state.consecutive_losses >= self.cfg.cooldown_after_losses:
                self.state.cooldown_until = (
                    datetime.utcnow() + timedelta(hours=self.cfg.cooldown_hours)
                )
                log_risk("COOLDOWN_TRIGGERED",
                         until=self.state.cooldown_until.isoformat(),
                         consecutive=self.state.consecutive_losses)
                self.state.consecutive_losses = 0
        else:
            self.state.consecutive_losses = 0

        self._check_survival_mode()
        self._check_profit_take()

    def get_allowed_leverage(self, requested: int) -> int:
        """Enforce leverage limits based on current state."""
        if self.state.survival_mode:
            return self.cfg.survival_leverage
        return requested

    def get_status(self) -> dict:
        return {
            'balance': round(self.state.balance, 2),
            'open_positions': len(self.state.open_positions),
            'daily_loss': round(self.state.daily_loss, 2),
            'consecutive_losses': self.state.consecutive_losses,
            'survival_mode': self.state.survival_mode,
            'cooldown_active': (
                self.state.cooldown_until is not None
                and datetime.utcnow() < self.state.cooldown_until
            ),
        }
