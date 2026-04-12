"""
scripts/walkforward_5m.py – Walk-forward validation for best 5m config.

Splits history into train/test windows and validates OOS performance.
Uses the best config from R3 sweep.

Usage:
    python -m scripts.walkforward_5m
"""
import sys, time, json
from pathlib import Path
from core.backtester import Backtester, BacktestConfig

DATA_DIR = "data/history/5m"
OUT_DIR  = Path("logs/sweep_5m")

# ── R3 winner: trail_20_8 (RSI 60-72 + ATR floor 0.6% + tight trail 2%/0.8%) ──
# Cross-window: W1 +375.5%, W2 +144.5%, W3 +227.3%, Avg +249.1%, AvgPF 1.22
BEST_CONFIG = dict(
    initial_capital=500.0,
    max_positions=5,
    fixed_leverage=3,
    rsi_entry_min=60.0,
    rsi_entry_max=72.0,
    min_close_ratio=0.55,
    min_margin=1.0,
    capital_floor=10.0,
    require_standard_symbols=True,
    exclude_symbols=["BTCDOMUSDT", "USDCUSDT"],
    equity_trail_pct=0.25,
    profit_lock_mult=1.5,
    profit_lock_ratio=0.4,
    ema_fast=108, ema_mid=252, ema_slow=600, ema_regime=2400,
    rsi_period=168, atr_period=168, vol_ma_period=240,
    breakout_lookback=240,
    volume_mult=3.0,
    breakout_margin=0.005,
    min_entry_score=0.25,
    atr_floor_pct=0.006,
    trailing_act_pct=0.020,
    trailing_dist_pct=0.008,
    sl_atr_mult={3: 5.0},
    max_hold_bars=288,
    rsi_exit_max=78,
    cooldown_bars=36,
    verbose=False,
)

# Walk-forward windows: (train_start, train_end, test_start, test_end)
WALK_FORWARD_WINDOWS = [
    # WF1: Train on 2021, test on 2022-H1
    ("2021-01-01", "2021-12-31", "2022-01-01", "2022-06-30"),
    # WF2: Train on 2022, test on 2023-H1
    ("2022-01-01", "2022-12-31", "2023-01-01", "2023-06-30"),
    # WF3: Train on 2023, test on 2024-H1
    ("2023-01-01", "2023-12-31", "2024-01-01", "2024-06-30"),
    # WF4: Train on 2024, test on 2025-Q1
    ("2024-01-01", "2024-12-31", "2025-01-01", "2025-04-12"),
]


def extract(result):
    if "error" in result:
        return dict(final=0, ret=-100, trades=0, wr=0, dd=100,
                    sharpe=None, pf=0, avg_hold=0, err=result["error"])
    return dict(
        final   = result.get("final_capital", 0),
        ret     = result.get("return_pct", -100),
        trades  = result.get("total_trades", 0),
        wr      = result.get("win_rate", 0),
        dd      = result.get("max_drawdown_pct", 100),
        sharpe  = result.get("sharpe_ratio"),
        pf      = result.get("profit_factor", 0),
        avg_hold= result.get("avg_hold_bars", 0),
        exits   = result.get("exit_reasons", {}),
        err     = None,
    )


def fmt(v):
    if v is None: return "   N/A"
    return f"{v:>6.2f}"


def run(config_overrides=None):
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cfg_dict = {**BEST_CONFIG}
    if config_overrides:
        cfg_dict.update(config_overrides)

    cfg = BacktestConfig(**cfg_dict)

    print("=" * 70)
    print("  WALK-FORWARD VALIDATION — 5m Best Config")
    print("=" * 70)
    print(f"  Config: RSI {cfg.rsi_entry_min}-{cfg.rsi_entry_max}, "
          f"ATR floor {cfg.atr_floor_pct}, trail {cfg.trailing_act_pct}/{cfg.trailing_dist_pct}")

    # load data
    bt_load = Backtester(cfg)
    prepared = bt_load.prepare_data(DATA_DIR)
    print(f"  Data loaded in {time.time()-t0:.0f}s")
    if "error" in prepared:
        print(f"  ERROR: {prepared['error']}"); return

    results = []
    print(f"\n  {'Window':<10} {'Phase':<6} {'Period':<25} {'Final':>7} {'Ret%':>7} "
          f"{'#Tr':>5} {'WR%':>5} {'DD%':>5} {'Shrp':>6} {'PF':>6}")
    print(f"  {'-'*85}")

    for i, (tr_s, tr_e, te_s, te_e) in enumerate(WALK_FORWARD_WINDOWS, 1):
        # Train
        ts = time.time()
        sl_train = Backtester.slice_prepared(prepared, tr_s, tr_e)
        bt = Backtester(cfg)
        raw_train = bt.run_prepared(sl_train)
        el = time.time() - ts
        m = extract(raw_train)
        results.append({"window": f"WF{i}", "phase": "TRAIN",
                        "period": f"{tr_s}~{tr_e}", **m})
        print(f"  WF{i:<7} {'TRAIN':<6} {tr_s}~{tr_e:<12} {m['final']:>7.1f} "
              f"{m['ret']:>7.1f} {m['trades']:>5} {m['wr']:>5.1f} {m['dd']:>5.1f} "
              f"{fmt(m['sharpe'])} {fmt(m['pf'])}  {el:.0f}s")
        del sl_train

        # Test (OOS)
        ts = time.time()
        sl_test = Backtester.slice_prepared(prepared, te_s, te_e)
        bt2 = Backtester(cfg)
        raw_test = bt2.run_prepared(sl_test)
        el = time.time() - ts
        m = extract(raw_test)
        results.append({"window": f"WF{i}", "phase": "TEST",
                        "period": f"{te_s}~{te_e}", **m})
        print(f"  {'':>9} {'TEST':<6} {te_s}~{te_e:<12} {m['final']:>7.1f} "
              f"{m['ret']:>7.1f} {m['trades']:>5} {m['wr']:>5.1f} {m['dd']:>5.1f} "
              f"{fmt(m['sharpe'])} {fmt(m['pf'])}  {el:.0f}s")
        del sl_test

    del prepared

    # Summary
    total = time.time() - t0
    train_results = [r for r in results if r["phase"] == "TRAIN"]
    test_results  = [r for r in results if r["phase"] == "TEST"]
    avg_train_ret = sum(r["ret"] for r in train_results) / len(train_results)
    avg_test_ret  = sum(r["ret"] for r in test_results) / len(test_results)
    avg_train_pf  = sum(r["pf"] for r in train_results) / len(train_results)
    avg_test_pf   = sum(r["pf"] for r in test_results) / len(test_results)
    oos_positive  = sum(1 for r in test_results if r["ret"] > 0)

    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD SUMMARY")
    print(f"{'='*70}")
    print(f"  Avg TRAIN return: {avg_train_ret:>+7.1f}%  PF: {avg_train_pf:.2f}")
    print(f"  Avg TEST  return: {avg_test_ret:>+7.1f}%  PF: {avg_test_pf:.2f}")
    print(f"  OOS profitable:   {oos_positive}/{len(test_results)} windows")
    print(f"  Total time:       {total:.0f}s ({total/60:.1f}m)")

    out_file = OUT_DIR / "walkforward_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "config": {k: v for k, v in cfg_dict.items() if k != "verbose"},
            "results": results,
            "summary": {
                "avg_train_ret": round(avg_train_ret, 2),
                "avg_test_ret": round(avg_test_ret, 2),
                "avg_train_pf": round(avg_train_pf, 3),
                "avg_test_pf": round(avg_test_pf, 3),
                "oos_positive": oos_positive,
                "oos_total": len(test_results),
            },
            "total_time_s": round(total, 1),
        }, f, indent=2, default=str)
    print(f"  Results → {out_file}")


if __name__ == "__main__":
    run()
