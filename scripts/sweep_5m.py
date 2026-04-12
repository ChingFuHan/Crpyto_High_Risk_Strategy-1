"""
scripts/sweep_5m.py – Multi-scenario 5m backtest sweep.

Loads 5m data once per indicator profile, then sweeps exit & entry
threshold parameters using the fast run_prepared() path.

Usage:
    python -m scripts.sweep_5m
    python -m scripts.sweep_5m --profile all
    python -m scripts.sweep_5m --train-start 2024-01-01 --train-end 2024-12-31
"""
import argparse, sys, time, json
from pathlib import Path
from core.backtester import Backtester, BacktestConfig

# ── defaults ────────────────────────────────────────────────────────────────
TRAIN_START = "2024-07-01"
TRAIN_END   = "2024-12-31"
DATA_DIR    = "data/history/5m"
OUT_DIR     = Path("logs/sweep_5m")

# ── common base (proven on 1h) ──────────────────────────────────────────────
BASE = dict(
    initial_capital=500.0,
    max_positions=5,
    fixed_leverage=3,
    volume_mult=1.5,
    rsi_entry_min=52.0,
    rsi_entry_max=80.0,
    min_close_ratio=0.55,
    min_margin=1.0,
    capital_floor=10.0,
    require_standard_symbols=True,
    exclude_symbols=["BTCDOMUSDT", "USDCUSDT"],
    equity_trail_pct=0.25,
    profit_lock_mult=1.5,
    profit_lock_ratio=0.4,
)

# ── indicator profiles ──────────────────────────────────────────────────────
PROFILES = {
    "12x": dict(
        ema_fast=108, ema_mid=252, ema_slow=600, ema_regime=2400,
        rsi_period=168, atr_period=168, vol_ma_period=240,
        breakout_lookback=240,
    ),
    "6x": dict(
        ema_fast=54, ema_mid=126, ema_slow=300, ema_regime=1200,
        rsi_period=84, atr_period=84, vol_ma_period=120,
        breakout_lookback=120,
    ),
    "native": dict(
        ema_fast=9, ema_mid=21, ema_slow=50, ema_regime=200,
        rsi_period=14, atr_period=14, vol_ma_period=20,
        breakout_lookback=20,
    ),
}

# ── scenario definitions: (tag, profile_key, override_dict) ─────────────────
SCENARIOS = [
    # ═══ 12× time-equivalent — same real-world signal timing as 1h ═══════
    ("12x_baseline", "12x", dict(
        trailing_act_pct=0.04, trailing_dist_pct=0.018,
        sl_atr_mult={3: 3.0}, max_hold_bars=1152,
        rsi_exit_max=85, cooldown_bars=60)),
    ("12x_tight_trail", "12x", dict(
        trailing_act_pct=0.025, trailing_dist_pct=0.012,
        sl_atr_mult={3: 3.0}, max_hold_bars=1152,
        rsi_exit_max=85, cooldown_bars=60)),
    ("12x_wide_trail", "12x", dict(
        trailing_act_pct=0.06, trailing_dist_pct=0.03,
        sl_atr_mult={3: 3.0}, max_hold_bars=1152,
        rsi_exit_max=85, cooldown_bars=60)),
    ("12x_wide_stop", "12x", dict(
        trailing_act_pct=0.04, trailing_dist_pct=0.018,
        sl_atr_mult={3: 5.0}, max_hold_bars=1152,
        rsi_exit_max=85, cooldown_bars=60)),
    ("12x_tight_stop", "12x", dict(
        trailing_act_pct=0.04, trailing_dist_pct=0.018,
        sl_atr_mult={3: 2.0}, max_hold_bars=1152,
        rsi_exit_max=85, cooldown_bars=60)),
    ("12x_short_hold", "12x", dict(
        trailing_act_pct=0.04, trailing_dist_pct=0.018,
        sl_atr_mult={3: 3.0}, max_hold_bars=576,
        rsi_exit_max=85, cooldown_bars=60)),
    ("12x_hi_vol", "12x", dict(
        trailing_act_pct=0.04, trailing_dist_pct=0.018,
        sl_atr_mult={3: 3.0}, max_hold_bars=1152,
        rsi_exit_max=85, cooldown_bars=60,
        volume_mult=2.5)),
    ("12x_narrow_rsi", "12x", dict(
        trailing_act_pct=0.04, trailing_dist_pct=0.018,
        sl_atr_mult={3: 3.0}, max_hold_bars=1152,
        rsi_exit_max=80, cooldown_bars=60,
        rsi_entry_min=55.0)),
    # Combined scenarios for 12x
    ("12x_safe_combo", "12x", dict(
        trailing_act_pct=0.06, trailing_dist_pct=0.025,
        sl_atr_mult={3: 5.0}, max_hold_bars=576,
        rsi_exit_max=80, cooldown_bars=60,
        volume_mult=2.5, rsi_entry_min=55.0)),
    ("12x_aggr_combo", "12x", dict(
        trailing_act_pct=0.025, trailing_dist_pct=0.01,
        sl_atr_mult={3: 5.0}, max_hold_bars=288,
        rsi_exit_max=78, cooldown_bars=36,
        volume_mult=2.0)),

    # ═══ 6× hybrid — halfway between 1h-equiv and native 5m ═════════════
    ("6x_baseline", "6x", dict(
        trailing_act_pct=0.04, trailing_dist_pct=0.018,
        sl_atr_mult={3: 3.0}, max_hold_bars=576,
        rsi_exit_max=85, cooldown_bars=30)),
    ("6x_wide_stop", "6x", dict(
        trailing_act_pct=0.04, trailing_dist_pct=0.018,
        sl_atr_mult={3: 5.0}, max_hold_bars=576,
        rsi_exit_max=85, cooldown_bars=30)),
    ("6x_combo", "6x", dict(
        trailing_act_pct=0.035, trailing_dist_pct=0.015,
        sl_atr_mult={3: 4.0}, max_hold_bars=432,
        rsi_exit_max=82, cooldown_bars=24,
        volume_mult=2.0, rsi_entry_min=54.0)),

    # ═══ native 5m — wide stops to handle micro-noise ═══════════════════
    ("nat_wide_scalp", "native", dict(
        trailing_act_pct=0.02, trailing_dist_pct=0.008,
        sl_atr_mult={3: 8.0}, max_hold_bars=48,
        rsi_exit_max=80, cooldown_bars=12,
        volume_mult=2.0)),
    ("nat_vwide_med", "native", dict(
        trailing_act_pct=0.04, trailing_dist_pct=0.018,
        sl_atr_mult={3: 10.0}, max_hold_bars=144,
        rsi_exit_max=85, cooldown_bars=24,
        volume_mult=3.0)),
    ("nat_ultra_wide", "native", dict(
        trailing_act_pct=0.06, trailing_dist_pct=0.03,
        sl_atr_mult={3: 12.0}, max_hold_bars=288,
        rsi_exit_max=85, cooldown_bars=36,
        volume_mult=3.0, rsi_entry_min=56.0)),
]


def build_config(profile_key: str, overrides: dict) -> BacktestConfig:
    kw = {**BASE, **PROFILES[profile_key], **overrides}
    kw["verbose"] = False
    return BacktestConfig(**kw)


def extract_metrics(result: dict) -> dict:
    """Pull key metrics from run_prepared output."""
    if "error" in result:
        return {
            "final": 0, "return_pct": -100, "trades": 0,
            "win_rate": 0, "max_dd": 100, "sharpe": None,
            "calmar": None, "avg_hold": 0, "pf": 0,
            "exit_reasons": {}, "error": result["error"],
        }
    return {
        "final":       result.get("final_capital", 0),
        "return_pct":  result.get("return_pct", -100),
        "trades":      result.get("total_trades", 0),
        "win_rate":    result.get("win_rate", 0),
        "max_dd":      result.get("max_drawdown_pct", 100),
        "sharpe":      result.get("sharpe_ratio"),
        "calmar":      result.get("calmar_ratio"),
        "avg_hold":    result.get("avg_hold_bars", 0),
        "pf":          result.get("profit_factor", 0),
        "exit_reasons": result.get("exit_reasons", {}),
        "error":       None,
    }


def run_sweep(args):
    t0_wall = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Filter scenarios by requested profile
    selected = [
        (tag, pkey, ov) for tag, pkey, ov in SCENARIOS
        if args.profile == "all" or pkey == args.profile
    ]
    if not selected:
        print(f"No scenarios for profile '{args.profile}'.")
        return

    # Group by profile so we load data once per group
    by_profile: dict = {}
    for tag, pkey, ov in selected:
        by_profile.setdefault(pkey, []).append((tag, ov))

    all_results = []

    for pkey, scenarios in by_profile.items():
        print(f"\n{'='*70}")
        print(f"  PROFILE: {pkey}  ({len(scenarios)} scenarios)")
        print(f"  Indicators: {PROFILES[pkey]}")
        print(f"{'='*70}")

        # ── prepare data with this profile's indicators ─────────────────
        ref_cfg = build_config(pkey, scenarios[0][1])
        bt_prep = Backtester(ref_cfg)
        t_load = time.time()
        print(f"  Loading {DATA_DIR} …")
        prepared = bt_prep.prepare_data(DATA_DIR)
        load_s = time.time() - t_load
        print(f"  Loaded in {load_s:.0f}s")

        if "error" in prepared:
            print(f"  ERROR: {prepared['error']}")
            continue

        # ── slice to training window ────────────────────────────────────
        t_slice = time.time()
        sliced = Backtester.slice_prepared(
            prepared, args.train_start, args.train_end,
        )
        slice_s = time.time() - t_slice
        tl = sliced.get("timeline", [])
        n_sym = len(sliced.get("symbols", {}))
        print(f"  Sliced → {len(tl):,} bars, {n_sym} symbols  ({slice_s:.0f}s)")

        if "error" in sliced:
            print(f"  ERROR: {sliced['error']}")
            continue

        # Free full prepared to save memory
        del prepared

        # ── run each scenario ───────────────────────────────────────────
        print(f"\n  {'Tag':<25} {'Final':>8} {'Ret%':>8} {'Trades':>7} "
              f"{'WR%':>6} {'DD%':>7} {'Sharpe':>7} {'PF':>6} {'Secs':>5}")
        print(f"  {'-'*85}")

        for tag, ov in scenarios:
            cfg = build_config(pkey, ov)
            bt = Backtester(cfg)
            t_run = time.time()
            raw_result = bt.run_prepared(sliced)
            elapsed = time.time() - t_run

            m = extract_metrics(raw_result)
            m["tag"] = tag
            m["profile"] = pkey
            m["elapsed"] = round(elapsed, 1)
            m["config_overrides"] = {k: v for k, v in ov.items()
                                      if k != "sl_atr_mult"}
            if "sl_atr_mult" in ov:
                m["config_overrides"]["sl_atr_3x"] = ov["sl_atr_mult"].get(3, "?")
            all_results.append(m)

            sharpe_s = f"{m['sharpe']:.2f}" if isinstance(m['sharpe'], (int, float)) else str(m['sharpe'])
            pf_s = f"{m['pf']:.2f}" if isinstance(m['pf'], (int, float)) else str(m['pf'])
            err = f" !! {m['error']}" if m["error"] else ""
            print(f"  {tag:<25} {m['final']:>8.2f} {m['return_pct']:>8.1f} "
                  f"{m['trades']:>7} {m['win_rate']:>6.1f} {m['max_dd']:>7.1f} "
                  f"{sharpe_s:>7} {pf_s:>6} {elapsed:>5.0f}{err}")

        # Free sliced data before next profile
        del sliced

    # ── final summary sorted by return ──────────────────────────────────
    total_wall = time.time() - t0_wall
    print(f"\n{'='*90}")
    print(f"  SWEEP COMPLETE — {len(all_results)} scenarios in "
          f"{total_wall:.0f}s ({total_wall/60:.1f} min)")
    print(f"  Training window: {args.train_start} → {args.train_end}")
    print(f"{'='*90}")
    print(f"  {'#':>3} {'Tag':<25} {'Final':>8} {'Ret%':>8} {'Trades':>7} "
          f"{'WR%':>6} {'DD%':>7} {'Sharpe':>7} {'Calmar':>7}")
    print(f"  {'-'*90}")
    ranked = sorted(all_results, key=lambda x: x["return_pct"], reverse=True)
    for i, r in enumerate(ranked, 1):
        sharpe_s = f"{r['sharpe']:.2f}" if isinstance(r['sharpe'], (int, float)) else str(r['sharpe'])
        calmar_s = f"{r['calmar']:.2f}" if isinstance(r['calmar'], (int, float)) else str(r['calmar'])
        print(f"  {i:>3} {r['tag']:<25} {r['final']:>8.2f} {r['return_pct']:>8.1f} "
              f"{r['trades']:>7} {r['win_rate']:>6.1f} {r['max_dd']:>7.1f} "
              f"{sharpe_s:>7} {calmar_s:>7}")

    # ── save results ────────────────────────────────────────────────────
    out_file = OUT_DIR / "sweep_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Results → {out_file}")

    # ── top-3 detail ────────────────────────────────────────────────────
    print(f"\n  TOP-3 DETAILS:")
    for i, r in enumerate(ranked[:3], 1):
        print(f"  #{i}  {r['tag']}:")
        print(f"       Return: {r['return_pct']:.1f}%  Final: {r['final']:.2f}")
        print(f"       Trades: {r['trades']}  WinRate: {r['win_rate']:.1f}%  AvgHold: {r['avg_hold']:.0f} bars")
        print(f"       MaxDD: {r['max_dd']:.1f}%  Sharpe: {r['sharpe']}  Calmar: {r['calmar']}  PF: {r['pf']}")
        print(f"       Exits: {r['exit_reasons']}")
        print(f"       Overrides: {r['config_overrides']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="5m multi-scenario sweep")
    ap.add_argument("--profile", default="12x",
                    choices=["12x", "6x", "native", "all"],
                    help="Indicator profile to sweep (default: 12x)")
    ap.add_argument("--train-start", default=TRAIN_START)
    ap.add_argument("--train-end", default=TRAIN_END)
    run_sweep(ap.parse_args())
