"""
Run Scanner — main entry point for the full trading pipeline.
scan -> signal -> strategy -> risk check -> execute (or paper trade)

Usage:
    python -m scripts.run_scanner              # paper mode (default)
    python -m scripts.run_scanner --live       # live mode (real orders!)
    python -m scripts.run_scanner --once       # single scan then exit
"""
import argparse
import time
import sys

sys.path.insert(0, '.')

from config.settings import SETTINGS
from core.scanner import scan_top_gainers
from core.signals import analyze_batch
from core.strategy import evaluate
from core.risk_manager import RiskManager
from core.executor import execute_market_order
from core.paper_trader import PaperTrader
from utils.logger import logger


def run_cycle(risk_mgr: RiskManager, paper: PaperTrader | None,
              live: bool = False):
    """Execute one full scan-analyze-decide-execute cycle."""
    # Step 1: Scan market
    top = scan_top_gainers()
    if top.empty:
        logger.info("No candidates found this cycle")
        return

    symbols = top['symbol'].tolist()
    logger.info(f"Scanning {len(symbols)} candidates: {symbols[:5]}...")

    # Step 2: Analyze signals
    signals = analyze_batch(symbols, SETTINGS.scanner.kline_interval)
    if not signals:
        logger.info("No actionable signals this cycle")
        return

    logger.info(f"Found {len(signals)} actionable signal(s)")

    # Step 3: Evaluate each signal through strategy + risk
    for sig in signals:
        balance = risk_mgr.state.balance if live else paper.balance
        decision = evaluate(sig, balance)

        if decision.action == 'SKIP':
            continue

        # Enforce risk-adjusted leverage
        decision.leverage = risk_mgr.get_allowed_leverage(decision.leverage)

        # Risk check
        allowed, reason = risk_mgr.can_open_position(
            decision.symbol, decision.action.split('_')[1],
            decision.margin_usdt, decision.leverage,
        )

        if not allowed:
            logger.warning(f"Risk blocked {decision.symbol}: {reason}")
            continue

        # Step 4: Execute
        if live:
            result = execute_market_order(decision)
            if result.success:
                risk_mgr.on_position_opened(
                    result.symbol, decision.action.split('_')[1],
                    result.margin, result.leverage,
                )
        else:
            # Paper trade
            success = paper.open_position(
                symbol=decision.symbol,
                side=decision.action.split('_')[1],
                price=decision.entry_price,
                amount_usd=decision.margin_usdt,
                leverage=decision.leverage,
                setup=decision.setup,
            )
            if success:
                risk_mgr.on_position_opened(
                    decision.symbol, decision.action.split('_')[1],
                    decision.margin_usdt, decision.leverage,
                )
                paper.print_status()

        # Only take the best signal per cycle to stay disciplined
        break


def main():
    parser = argparse.ArgumentParser(description='Crypto Scanner & Trader')
    parser.add_argument('--live', action='store_true', help='Enable live trading (real orders!)')
    parser.add_argument('--once', action='store_true', help='Single scan then exit')
    parser.add_argument('--interval', type=int, default=None, help='Scan interval in seconds')
    args = parser.parse_args()

    mode = "LIVE" if args.live else "PAPER"
    logger.info(f"Starting scanner in {mode} mode")

    if args.live:
        logger.warning("=" * 50)
        logger.warning("  LIVE MODE — REAL MONEY AT RISK!")
        logger.warning("=" * 50)

    paper = None if args.live else PaperTrader(SETTINGS.initial_capital)
    initial_balance = SETTINGS.initial_capital
    if paper:
        initial_balance = paper.balance
    risk_mgr = RiskManager(initial_balance)

    interval = args.interval or SETTINGS.scanner.scan_interval_seconds

    if args.once:
        run_cycle(risk_mgr, paper, args.live)
        return

    logger.info(f"Scan interval: {interval}s — press Ctrl+C to stop")
    while True:
        try:
            run_cycle(risk_mgr, paper, args.live)
            time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Scanner stopped by user")
            break
        except Exception as e:
            logger.error(f"Cycle error: {e}")
            time.sleep(interval)


if __name__ == '__main__':
    main()
