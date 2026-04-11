"""
Run Paper Trading — interactive paper trade management

Usage:
    python -m scripts.run_paper status
    python -m scripts.run_paper open SYMBOL SIDE PRICE AMOUNT LEVERAGE
    python -m scripts.run_paper close SYMBOL PRICE
    python -m scripts.run_paper reset
"""
import sys
sys.path.insert(0, '.')

from core.paper_trader import PaperTrader
from config.settings import SETTINGS


def main():
    trader = PaperTrader(SETTINGS.initial_capital)

    if len(sys.argv) < 2:
        trader.print_status()
        print("Commands: status | open | close | reset")
        return

    cmd = sys.argv[1].lower()

    if cmd == 'status':
        trader.print_status()

    elif cmd == 'open':
        if len(sys.argv) < 7:
            print("Usage: open SYMBOL SIDE PRICE AMOUNT LEVERAGE")
            print("Example: open BTC/USDT:USDT LONG 65000 100 3")
            return
        symbol = sys.argv[2]
        side = sys.argv[3].upper()
        price = float(sys.argv[4])
        amount = float(sys.argv[5])
        leverage = int(sys.argv[6])
        trader.open_position(symbol, side, price, amount, leverage)
        trader.print_status()

    elif cmd == 'close':
        if len(sys.argv) < 4:
            print("Usage: close SYMBOL CURRENT_PRICE")
            return
        symbol = sys.argv[2]
        price = float(sys.argv[3])
        pnl = trader.close_position(symbol, price)
        if pnl is not None:
            emoji = "✅" if pnl >= 0 else "❌"
            print(f"{emoji} PnL: {pnl:+.2f} USDT")
        trader.print_status()

    elif cmd == 'reset':
        trader.portfolio.balance = SETTINGS.initial_capital
        trader.portfolio.positions = []
        trader._save()
        print(f"Portfolio reset to {SETTINGS.initial_capital} USDT")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == '__main__':
    main()
