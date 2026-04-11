"""
Targeted optimizer for the long-only 3x / max-5 backtest variant.

It reuses a single prepared market snapshot and sweeps stricter entry filters.
Outputs:
  - data/optimization_long_only_3x_max5.csv
  - data/optimization_long_only_3x_max5.json
"""
import argparse
import json
import os
import sys
import time
from itertools import product
from pathlib import Path

import pandas as pd

# ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.backtester import Backtester, BacktestConfig


BASE_EXCLUDES = ["BTCDOMUSDT", "USDCUSDT"]
SMALLCAP_EXTRA_EXCLUDES = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "TRXUSDT", "LINKUSDT", "LTCUSDT", "DOTUSDT", "BCHUSDT",
    "ETCUSDT", "AVAXUSDT",
]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Optimize long-only 3x / max-5 filters")
    parser.add_argument("--data", default="data/history/1h",
                        help="Directory with OHLCV CSVs (default: data/history/1h)")
    parser.add_argument("--top", type=int, default=5,
                        help="How many top scenarios to print")
    parser.add_argument("--output-prefix", default="optimization_long_only_3x_max5",
                        help="Output prefix under data/")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from an existing output file if present")
    parser.add_argument("--universe", choices=["broad", "smallcap"], default="broad",
                        help="Universe preset for tradable symbols")
    parser.add_argument("--vol-mults", nargs="*", type=float, default=[1.5, 1.8, 2.2],
                        help="Volume ratio thresholds to sweep")
    parser.add_argument("--rsi-mins", nargs="*", type=float, default=[52.0, 56.0, 60.0],
                        help="Minimum RSI thresholds to sweep")
    parser.add_argument("--rsi-maxs", nargs="*", type=float, default=[74.0, 78.0],
                        help="Maximum RSI thresholds to sweep")
    parser.add_argument("--close-ratios", nargs="*", type=float, default=[0.55, 0.65, 0.75],
                        help="Minimum close-ratio thresholds to sweep")
    return parser


def universe_excludes(name: str) -> list[str]:
    excludes = list(BASE_EXCLUDES)
    if name == "smallcap":
        excludes.extend(SMALLCAP_EXTRA_EXCLUDES)
    return excludes


def make_scenarios(args: argparse.Namespace) -> list[dict]:
    scenarios = [{
        "name": "baseline",
        "volume_mult": 1.5,
        "rsi_entry_min": 52.0,
        "rsi_entry_max": 80.0,
        "min_close_ratio": 0.55,
    }]
    for vol_mult, rsi_min, rsi_max, close_ratio in product(
        args.vol_mults, args.rsi_mins, args.rsi_maxs, args.close_ratios
    ):
        if rsi_min >= rsi_max:
            continue
        scenarios.append({
            "name": f"v{vol_mult:g}_r{rsi_min:g}-{rsi_max:g}_c{close_ratio:g}",
            "volume_mult": vol_mult,
            "rsi_entry_min": rsi_min,
            "rsi_entry_max": rsi_max,
            "min_close_ratio": close_ratio,
        })
    deduped = {}
    for scenario in scenarios:
        deduped[scenario["name"]] = scenario
    return list(deduped.values())


def run_scenario(prepared: dict, scenario: dict, excludes: list[str]) -> dict:
    cfg = BacktestConfig(
        initial_capital=500.0,
        max_positions=5,
        fixed_leverage=3,
        min_margin=1.0,
        capital_floor=10.0,
        require_standard_symbols=True,
        exclude_symbols=excludes,
        volume_mult=scenario["volume_mult"],
        rsi_entry_min=scenario["rsi_entry_min"],
        rsi_entry_max=scenario["rsi_entry_max"],
        min_close_ratio=scenario["min_close_ratio"],
        verbose=False,
    )
    bt = Backtester(cfg)
    started = time.time()
    report = bt.run_prepared(prepared)
    elapsed = round(time.time() - started, 2)
    result = {
        "scenario": scenario["name"],
        "volume_mult": scenario["volume_mult"],
        "rsi_min": scenario["rsi_entry_min"],
        "rsi_max": scenario["rsi_entry_max"],
        "close_ratio": scenario["min_close_ratio"],
        "elapsed_sec": elapsed,
    }
    result.update(report)
    return result


def sort_key(row: dict) -> tuple:
    profit_factor = row.get("profit_factor")
    if profit_factor == "∞":
        profit_factor = 999.0
    return (
        float(row.get("final_capital", 0.0)),
        float(profit_factor or 0.0),
        float(row.get("win_rate", 0.0)),
        -float(row.get("max_drawdown_pct", 999.0)),
    )


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    base_cfg = BacktestConfig(verbose=False)
    prepared = Backtester(base_cfg).prepare_data(args.data)
    if "error" in prepared:
        print(json.dumps(prepared, ensure_ascii=False))
        sys.exit(1)

    excludes = universe_excludes(args.universe)
    scenarios = make_scenarios(args)
    results = []
    out_dir = Path("data")
    out_dir.mkdir(exist_ok=True)
    csv_path = out_dir / f"{args.output_prefix}.csv"
    json_path = out_dir / f"{args.output_prefix}.json"

    seen = set()
    if args.resume and json_path.exists():
        results = json.loads(json_path.read_text(encoding="utf-8"))
        seen = {row["scenario"] for row in results}
        print(f"Resuming from {json_path} with {len(seen)} completed scenarios")

    print(f"Prepared market snapshot. Running {len(scenarios)} scenarios on universe={args.universe} ...")
    for idx, scenario in enumerate(scenarios, start=1):
        if scenario["name"] in seen:
            print(f"[{idx:>2}/{len(scenarios)}] {scenario['name']} (skip)")
            continue
        print(f"[{idx:>2}/{len(scenarios)}] {scenario['name']}")
        results.append(run_scenario(prepared, scenario, excludes))
        ranked = sorted(results, key=sort_key, reverse=True)
        pd.DataFrame(ranked).to_csv(csv_path, index=False)
        json_path.write_text(json.dumps(ranked, indent=2, ensure_ascii=False), encoding="utf-8")

    ranked = sorted(results, key=sort_key, reverse=True)
    pd.DataFrame(ranked).to_csv(csv_path, index=False)
    json_path.write_text(json.dumps(ranked, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print(f"Saved ranked results to {csv_path} and {json_path}")
    print()
    print("Top scenarios:")
    top_rows = ranked[:args.top]
    for row in top_rows:
        print(
            f"{row['scenario']:<24} "
            f"final={row.get('final_capital', 0):>8.2f} "
            f"ret={row.get('return_pct', 0):>7.2f}% "
            f"pf={row.get('profit_factor')} "
            f"wr={row.get('win_rate', 0):>6.2f}% "
            f"dd={row.get('max_drawdown_pct', 0):>6.2f}% "
            f"trades={row.get('total_trades', 0)}"
        )


if __name__ == "__main__":
    main()
