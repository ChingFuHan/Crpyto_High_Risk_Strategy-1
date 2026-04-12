"""
Optimizer for 5m timeframe backtest.

Reuses a single prepared market snapshot and sweeps exit parameters.
Exit tuning is proven to matter more than entry tuning (from 1h research).

Usage:
    python -m scripts.optimize_5m
    python -m scripts.optimize_5m --train-start 2022-01-01 --train-end 2024-12-31
"""
import argparse
import json
import os
import sys
import time
from itertools import product
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.backtester import Backtester, BacktestConfig

BASE_EXCLUDES = ["BTCDOMUSDT", "USDCUSDT"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Optimize 5m backtest parameters")
    p.add_argument("--data", default="data/history/5m")
    p.add_argument("--train-start", default=None,
                   help="Training window start (default: all data)")
    p.add_argument("--train-end", default=None,
                   help="Training window end (default: all data)")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--output-prefix", default="opt_5m_exit_v1")
    p.add_argument("--resume", action="store_true")
    return p


def make_scenarios() -> list[dict]:
    """Generate exit-focused parameter sweep for 5m timeframe."""
    scenarios = []

    # Base: time-scaled from best 1h params
    trail_acts = [0.03, 0.04, 0.06, 0.08]
    trail_dists = [0.012, 0.018, 0.025, 0.035]
    max_holds = [288, 576, 1152]          # 1 day, 2 days, 4 days at 5m
    rsi_exits = [80, 85, 90]
    cooldowns = [12, 36, 60]              # 1h, 3h, 5h at 5m
    sl_atr_mults = [2.5, 3.0, 3.5]

    # Full sweep is huge; use targeted combinations
    # Phase 1: sweep trail_act × trail_dist (most impactful from 1h research)
    for ta, td in product(trail_acts, trail_dists):
        if td >= ta:
            continue  # trail distance must be less than activation
        scenarios.append({
            "name": f"trail_ta{ta}_td{td}",
            "trailing_act_pct": ta,
            "trailing_dist_pct": td,
            "max_hold_bars": 576,
            "rsi_exit_max": 85,
            "cooldown_bars": 36,
            "sl_atr_3x": 3.0,
        })

    # Phase 2: sweep max_hold × rsi_exit with best trail defaults
    for mh, re in product(max_holds, rsi_exits):
        scenarios.append({
            "name": f"hold_mh{mh}_re{re}",
            "trailing_act_pct": 0.04,
            "trailing_dist_pct": 0.018,
            "max_hold_bars": mh,
            "rsi_exit_max": re,
            "cooldown_bars": 36,
            "sl_atr_3x": 3.0,
        })

    # Phase 3: sweep sl_atr_mult × cooldown
    for sl, cd in product(sl_atr_mults, cooldowns):
        scenarios.append({
            "name": f"sl_sl{sl}_cd{cd}",
            "trailing_act_pct": 0.04,
            "trailing_dist_pct": 0.018,
            "max_hold_bars": 576,
            "rsi_exit_max": 85,
            "cooldown_bars": cd,
            "sl_atr_3x": sl,
        })

    # Deduplicate
    deduped = {}
    for s in scenarios:
        deduped[s["name"]] = s
    return list(deduped.values())


def run_scenario(prepared: dict, scenario: dict) -> dict:
    cfg = BacktestConfig(
        initial_capital=500.0,
        max_positions=5,
        fixed_leverage=3,
        min_margin=1.0,
        capital_floor=10.0,
        require_standard_symbols=True,
        exclude_symbols=BASE_EXCLUDES,
        volume_mult=1.5,
        rsi_entry_min=52.0,
        rsi_entry_max=80.0,
        min_close_ratio=0.55,
        ema_regime=2400,
        trailing_act_pct=scenario["trailing_act_pct"],
        trailing_dist_pct=scenario["trailing_dist_pct"],
        max_hold_bars=scenario["max_hold_bars"],
        rsi_exit_max=scenario["rsi_exit_max"],
        cooldown_bars=scenario["cooldown_bars"],
        sl_atr_mult={3: scenario["sl_atr_3x"]},
        verbose=False,
    )
    bt = Backtester(cfg)
    t0 = time.time()
    report = bt.run_prepared(prepared)
    elapsed = round(time.time() - t0, 1)
    result = {"scenario": scenario["name"], "elapsed_sec": elapsed}
    result.update(scenario)
    result.update(report)
    return result


def sort_key(row: dict) -> tuple:
    pf = row.get("profit_factor")
    if pf == "∞":
        pf = 999.0
    return (
        float(row.get("final_capital", 0)),
        float(pf or 0),
        float(row.get("win_rate", 0)),
        -float(row.get("max_drawdown_pct", 999)),
    )


def main():
    args = build_parser().parse_args()

    print("Loading 5m data (this may take several minutes) ...")
    base_cfg = BacktestConfig(verbose=True, ema_regime=2400)
    prepared = Backtester(base_cfg).prepare_data(args.data)
    if "error" in prepared:
        print(json.dumps(prepared))
        sys.exit(1)

    # Slice to training window if specified
    if args.train_start or args.train_end:
        prepared = Backtester.slice_prepared(prepared, args.train_start, args.train_end)
        if "error" in prepared:
            print(json.dumps(prepared))
            sys.exit(1)
        print(f"  Sliced to {args.train_start or 'start'} → {args.train_end or 'end'}")
        print(f"  Timeline bars: {len(prepared['timeline']):,}")

    scenarios = make_scenarios()
    results = []
    out_dir = Path("data")
    out_dir.mkdir(exist_ok=True)
    csv_path = out_dir / f"{args.output_prefix}.csv"
    json_path = out_dir / f"{args.output_prefix}.json"

    seen = set()
    if args.resume and json_path.exists():
        results = json.loads(json_path.read_text(encoding="utf-8"))
        seen = {r["scenario"] for r in results}
        print(f"Resuming with {len(seen)} completed scenarios")

    print(f"\nRunning {len(scenarios)} scenarios ...")
    total_start = time.time()
    for idx, scenario in enumerate(scenarios, 1):
        if scenario["name"] in seen:
            print(f"[{idx:>3}/{len(scenarios)}] {scenario['name']} (skip)")
            continue
        print(f"[{idx:>3}/{len(scenarios)}] {scenario['name']}", end="", flush=True)
        result = run_scenario(prepared, scenario)
        elapsed = result.get("elapsed_sec", 0)
        final = result.get("final_capital", 0)
        ret = result.get("return_pct", 0)
        print(f"  final={final:>8.2f}  ret={ret:>+7.2f}%  ({elapsed:.0f}s)")
        results.append(result)

        # Save incrementally
        ranked = sorted(results, key=sort_key, reverse=True)
        pd.DataFrame(ranked).to_csv(csv_path, index=False)
        json_path.write_text(json.dumps(ranked, indent=2, ensure_ascii=False), encoding="utf-8")

    total_elapsed = time.time() - total_start
    ranked = sorted(results, key=sort_key, reverse=True)
    pd.DataFrame(ranked).to_csv(csv_path, index=False)
    json_path.write_text(json.dumps(ranked, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nTotal optimization time: {total_elapsed/60:.1f} min")
    print(f"Saved to {csv_path} and {json_path}\n")
    print("Top scenarios:")
    for row in ranked[:args.top]:
        print(
            f"  {row['scenario']:<28} "
            f"final={row.get('final_capital', 0):>8.2f} "
            f"ret={row.get('return_pct', 0):>+7.2f}% "
            f"pf={row.get('profit_factor')} "
            f"wr={row.get('win_rate', 0):>5.1f}% "
            f"dd={row.get('max_drawdown_pct', 0):>5.1f}% "
            f"trades={row.get('total_trades', 0)}"
        )


if __name__ == "__main__":
    main()
