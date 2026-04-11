"""
Structured logger using loguru
"""
import sys
from pathlib import Path
from loguru import logger

LOG_DIR = Path(__file__).resolve().parent.parent / 'logs'
LOG_DIR.mkdir(exist_ok=True)

# Remove default handler
logger.remove()

# Console output — concise
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}",
    level="INFO",
    colorize=True,
)

# Trade log — append, structured
logger.add(
    LOG_DIR / "trades.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {message}",
    level="INFO",
    rotation="10 MB",
    retention="30 days",
    filter=lambda record: "trade" in record["extra"],
)

# System log — all events
logger.add(
    LOG_DIR / "system.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {module}:{function}:{line} | {message}",
    level="DEBUG",
    rotation="10 MB",
    retention="30 days",
)

trade_logger = logger.bind(trade=True)


def log_trade(action: str, symbol: str, **kwargs):
    """Log a trade event with structured data."""
    details = " | ".join(f"{k}={v}" for k, v in kwargs.items())
    trade_logger.info(f"[TRADE] {action} {symbol} | {details}")


def log_signal(symbol: str, signal_type: str, strength: float, **kwargs):
    details = " | ".join(f"{k}={v}" for k, v in kwargs.items())
    logger.info(f"[SIGNAL] {signal_type} {symbol} | strength={strength:.2f} | {details}")


def log_risk(event: str, **kwargs):
    details = " | ".join(f"{k}={v}" for k, v in kwargs.items())
    logger.warning(f"[RISK] {event} | {details}")
