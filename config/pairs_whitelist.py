"""
Pairs whitelist / blacklist management
"""

BLACKLIST = {
    'BUSDUSDT', 'USDCUSDT', 'TUSDUSDT', 'DAIUSDT',
    'FDUSDUSDT', 'EURUSDT',
}

WHITELIST: set = set()  # empty = auto-discover mode

QUOTE_CURRENCY = 'USDT'
MIN_24H_VOLUME_USDT = 500_000
