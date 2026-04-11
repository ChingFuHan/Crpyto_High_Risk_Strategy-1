"""
Exchange — ccxt Binance USDⓈ-M wrapper
Provides a singleton exchange connection with testnet support.
"""
import os
import ccxt
from utils.logger import logger


_exchange_instance: ccxt.binanceusdm | None = None


def get_exchange(testnet: bool | None = None) -> ccxt.binanceusdm:
    """Return a shared ccxt binanceusdm instance."""
    global _exchange_instance
    if _exchange_instance is not None:
        return _exchange_instance

    if testnet is None:
        testnet = os.getenv('BINANCE_TESTNET', 'true').lower() == 'true'

    api_key = os.getenv('BINANCE_API_KEY', '')
    api_secret = os.getenv('BINANCE_API_SECRET', '')

    config = {
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'},
    }

    if api_key and api_key != 'your_api_key_here':
        config['apiKey'] = api_key
        config['secret'] = api_secret

    if testnet:
        config['sandbox'] = True
        logger.info("Exchange: using TESTNET mode")
    else:
        logger.warning("Exchange: using LIVE mode — real money at risk!")

    _exchange_instance = ccxt.binanceusdm(config)
    logger.info("Exchange connection initialized")
    return _exchange_instance


def reset_exchange():
    """Reset the singleton (useful for testing)."""
    global _exchange_instance
    _exchange_instance = None
