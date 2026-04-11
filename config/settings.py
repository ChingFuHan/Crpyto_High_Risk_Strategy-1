"""
Unified Settings — merged from Copilot (dataclass config) + Codex (strategy params)
"""
from dataclasses import dataclass, field
from typing import Dict, List
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass
class LeverageConfig:
    high_signal: int = 5      # signal_strength >= 0.8
    medium_signal: int = 3    # signal_strength >= 0.5
    low_signal: int = 1       # signal_strength < 0.5
    short_max: int = 3


@dataclass
class RiskConfig:
    max_loss_per_trade: float = 0.15       # R1: single trade max loss ratio
    max_daily_loss: float = 0.40           # R3: daily max loss ratio
    max_positions: int = 3                 # R2: concurrent positions
    max_position_size: float = 0.30        # single position size cap
    cooldown_after_losses: int = 3         # R4: consecutive stop-losses before cooldown
    cooldown_hours: float = 2.0            # R4: cooldown duration
    survival_threshold: float = 200.0      # R5: switch to 1x below this
    survival_leverage: int = 1             # R5: leverage in survival mode
    recovery_threshold: float = 400.0      # R5: resume normal above this
    profit_take_threshold: float = 2000.0  # R6: take profit above this
    profit_take_ratio: float = 0.50        # R6: withdraw 50% profit
    max_5x_positions: int = 1              # max concurrent 5x positions


@dataclass
class LongEntryConfig:
    volume_multiplier: float = 3.0
    rsi_breakout: float = 60.0
    kline_interval: str = '5m'

    tp_levels: List[Dict] = field(default_factory=lambda: [
        {"ratio": 0.50, "target_pct": 0.15},   # 50% @ +15%
        {"ratio": 0.30, "target_pct": 0.30},   # 30% @ +30%
        {"ratio": 0.20, "target_pct": None},    # 20% trailing
    ])

    sl_by_leverage: Dict[int, float] = field(default_factory=lambda: {
        1: 0.08,   # 1x -> -8%
        3: 0.05,   # 3x -> -5%
        5: 0.03,   # 5x -> -3%
    })


@dataclass
class ShortEntryConfig:
    rsi_overbought: float = 80.0
    volume_decline: bool = True
    upper_shadow_ratio: float = 2.0
    tp_target_pct: float = 0.10

    sl_by_leverage: Dict[int, float] = field(default_factory=lambda: {
        1: 0.05,
        3: 0.03,
    })


@dataclass
class ScannerConfig:
    scan_interval_seconds: int = 30
    kline_interval: str = '5m'
    lookback_candles: int = 100
    min_volume_usdt: float = 500_000.0
    top_n: int = 10


@dataclass
class Settings:
    leverage: LeverageConfig = field(default_factory=LeverageConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    long_entry: LongEntryConfig = field(default_factory=LongEntryConfig)
    short_entry: ShortEntryConfig = field(default_factory=ShortEntryConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)

    initial_capital: float = 500.0
    margin_type: str = 'ISOLATED'
    testnet: bool = True

    trading_fee_rate: float = 0.0004  # 0.04% taker fee
    maintenance_margin_rate: float = 0.02  # 2% for most pairs


SETTINGS = Settings(
    testnet=os.getenv('BINANCE_TESTNET', 'true').lower() == 'true'
)
