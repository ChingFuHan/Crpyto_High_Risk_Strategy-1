"""
Run the momentum-chase (追高) backtest.

Usage:
    python -m scripts.run_backtest
    python -m scripts.run_backtest --data data/history/1h
    python -m scripts.run_backtest --capital 500 --max-pos 5
"""
import argparse
import sys
import os

# ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.backtester import Backtester, BacktestConfig


def main():
    ap = argparse.ArgumentParser(description="Momentum-chase backtest (long only)")
    ap.add_argument("--data", default="data/history/1h",
                    help="Directory with OHLCV CSVs (default: data/history/1h)")
    ap.add_argument("--capital", type=float, default=500.0,
                    help="Initial capital in USDT (default: 500)")
    ap.add_argument("--max-pos", type=int, default=5,
                    help="Max concurrent positions (default: 5)")
    args = ap.parse_args()

    if not os.path.isdir(args.data):
        print(f"✗ Data directory not found: {args.data}")
        print("  Run  python -m scripts.download_history  first.")
        sys.exit(1)

    cfg = BacktestConfig(
        initial_capital=args.capital,
        max_positions=args.max_pos,
    )
    bt = Backtester(cfg)
    report = bt.run(args.data)

    # ── pretty-print report ──────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  BACKTEST REPORT — Momentum Chase 追高 (Long Only)")
    print("=" * 60)

    if "error" in report:
        print(f"  Error: {report['error']}")
        return

    simple = [
        ("Initial Capital",  f"{report['initial_capital']:.2f} USDT"),
        ("Final Capital",    f"{report['final_capital']:.2f} USDT"),
        ("Total PnL",        f"{report['total_pnl']:+.2f} USDT"),
        ("Return",           f"{report['return_pct']:+.2f} %"),
        ("Total Trades",     report["total_trades"]),
        ("Wins / Losses",    f"{report['wins']} / {report['losses']}"),
        ("Win Rate",         f"{report['win_rate']:.1f} %"),
        ("Avg Win",          f"{report['avg_win']:+.2f} USDT"),
        ("Avg Loss",         f"{report['avg_loss']:+.2f} USDT"),
        ("Profit Factor",    report["profit_factor"]),
        ("Max Drawdown",     f"{report['max_drawdown_pct']:.1f} %"),
        ("Avg Hold",         f"{report['avg_hold_bars']:.0f} bars"),
    ]
    for label, val in simple:
        print(f"  {label:<20} {val}")

    print()
    print("  Exit Reasons:")
    for reason, cnt in report.get("exit_reasons", {}).items():
        print(f"    {reason:<20} {cnt}")

    print()
    print("  Leverage Distribution:")
    for lev, cnt in sorted(report.get("leverage_dist", {}).items()):
        print(f"    {lev:<6} {cnt}")

    print()
    print("  Top Symbols (by PnL):")
    for sym, pnl in report.get("top_symbols_pnl", {}).items():
        print(f"    {sym:<18} {pnl:+.2f}")

    print("=" * 60)

    # ── save ─────────────────────────────────────────────────────────────
    bt.save_results()


if __name__ == "__main__":
    main()
