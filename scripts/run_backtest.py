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
    ap.add_argument("--out-prefix", default="backtest",
                    help="Output file prefix under data/")
    ap.add_argument("--capital", type=float, default=500.0,
                    help="Initial capital in USDT (default: 500)")
    ap.add_argument("--max-pos", type=int, default=5,
                    help="Max concurrent positions (default: 5)")
    ap.add_argument("--fixed-lev", type=int, default=None,
                    help="Use a fixed leverage instead of score tiers")
    ap.add_argument("--vol-mult", type=float, default=1.5,
                    help="Minimum volume ratio for entry")
    ap.add_argument("--rsi-min", type=float, default=52.0,
                    help="Minimum RSI for entry")
    ap.add_argument("--rsi-max", type=float, default=80.0,
                    help="Maximum RSI for entry")
    ap.add_argument("--close-ratio", type=float, default=0.55,
                    help="Minimum close-within-candle ratio for entry")
    ap.add_argument("--min-margin", type=float, default=5.0,
                    help="Minimum margin required to open a trade")
    ap.add_argument("--capital-floor", type=float, default=10.0,
                    help="Minimum free capital required before new entries")
    ap.add_argument("--sl-atr-3x", type=float, default=3.0,
                    help="ATR multiple used for the 3x stop-loss")
    ap.add_argument("--trail-act", type=float, default=0.06,
                    help="Profit percentage that activates the trailing stop")
    ap.add_argument("--trail-dist", type=float, default=0.025,
                    help="Trailing-stop distance once activated")
    ap.add_argument("--max-hold", type=int, default=96,
                    help="Maximum holding period in bars")
    ap.add_argument("--rsi-exit-max", type=float, default=85.0,
                    help="Exit if RSI rises above this threshold")
    ap.add_argument("--standard-symbols", action="store_true",
                    help="Only trade symbols matching ^[A-Z0-9]+USDT$")
    ap.add_argument("--exclude-symbols", nargs="*", default=None,
                    help="Explicit symbol blacklist for the tradable universe")
    ap.add_argument("--no-profit-lock", action="store_true",
                    help="Disable the progressive profit-lock feature")
    ap.add_argument("--start-date", default=None,
                    help="Inclusive backtest start timestamp (YYYY-MM-DD or full datetime)")
    ap.add_argument("--end-date", default=None,
                    help="Inclusive backtest end timestamp (YYYY-MM-DD or full datetime)")
    args = ap.parse_args()

    if not os.path.isdir(args.data):
        print(f"✗ Data directory not found: {args.data}")
        print("  Run  python -m scripts.download_history  first.")
        sys.exit(1)

    cfg = BacktestConfig(
        initial_capital=args.capital,
        max_positions=args.max_pos,
        fixed_leverage=args.fixed_lev,
        volume_mult=args.vol_mult,
        rsi_entry_min=args.rsi_min,
        rsi_entry_max=args.rsi_max,
        min_close_ratio=args.close_ratio,
        min_margin=args.min_margin,
        capital_floor=args.capital_floor,
        sl_atr_mult={3: args.sl_atr_3x},
        trailing_act_pct=args.trail_act,
        trailing_dist_pct=args.trail_dist,
        max_hold_bars=args.max_hold,
        rsi_exit_max=args.rsi_exit_max,
        require_standard_symbols=args.standard_symbols,
        exclude_symbols=args.exclude_symbols or [],
    )
    if args.no_profit_lock:
        cfg.profit_lock_mult = 10_000.0
        cfg.profit_lock_ratio = 0.0
    bt = Backtester(cfg)
    prepared = bt.prepare_data(args.data)
    if "error" in prepared:
        report = prepared
    else:
        prepared = bt.slice_prepared(prepared, args.start_date, args.end_date)
        report = bt.run_prepared(prepared)

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
        ("  Locked Profit",  f"{report.get('locked_profit', 0):.2f} USDT"),
        ("  Trading Capital", f"{report.get('trading_capital', 0):.2f} USDT"),
        ("Total PnL",        f"{report['total_pnl']:+.2f} USDT"),
        ("Return",           f"{report['return_pct']:+.2f} %"),
        ("Annualized",       f"{report.get('annualized_return_pct', 0):+.2f} %" if report.get('annualized_return_pct') is not None else "N/A"),
        ("Sharpe",           report.get("sharpe_ratio", "N/A") if report.get("sharpe_ratio") is not None else "N/A"),
        ("Calmar",           report.get("calmar_ratio", "N/A") if report.get("calmar_ratio") is not None else "N/A"),
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

    print()
    print("  Worst Symbols (by PnL):")
    for sym, pnl in report.get("worst_symbols_pnl", {}).items():
        print(f"    {sym:<18} {pnl:+.2f}")

    print("=" * 60)

    # ── save ─────────────────────────────────────────────────────────────
    bt.save_results(prefix=args.out_prefix, summary=report)


if __name__ == "__main__":
    main()
