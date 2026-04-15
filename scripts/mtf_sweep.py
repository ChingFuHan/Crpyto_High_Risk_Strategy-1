"""
Multi-Timeframe (MTF) Sweep — 1h + 15m + 5m trend alignment.

Concept:
  - Simulation runs at 5m resolution (finest granularity)
  - For each 5m bar, we look up the corresponding 15m and 1h trend state
  - Entry requires ALL three timeframes to show bullish trend (trend_up=True)
  - This acts as a cross-TF confirmation filter reducing false signals

Approach:
  1. Load and compute indicators for 1h, 15m, 5m independently
  2. Build lookup dictionaries: trend_up state for each (symbol, timestamp) on 1h and 15m
  3. Inject these as an external filter into the 5m simulation
  4. Walk-forward validate the combined strategy
"""

import json, sys, os, time, gc
from pathlib import Path
from datetime import date, datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.backtester import Backtester, BacktestConfig
import pandas as pd
import numpy as np

OUT_DIR = Path("logs/comprehensive_sweep")

COMMON = dict(
    initial_capital=500.0, max_positions=5, fixed_leverage=3,
    fee_rate=0.0008, slippage_rate=0.0005,
    funding_rate_worst=0.0002, funding_rate_avg=0.0001,
    funding_rate_blend_worst=0.25, funding_rate_blend_avg=0.75,
    min_close_ratio=0.55, min_margin=1.0, capital_floor=10.0,
    require_standard_symbols=True,
    exclude_symbols=["BTCDOMUSDT", "USDCUSDT"],
    equity_trail_pct=0.25, profit_lock_mult=1.5, profit_lock_ratio=0.4,
    min_entry_score=0.25, breakout_margin=0.005, rsi_exit_max=78,
    verbose=False,
)

# Best configs from single-TF sweeps (will be loaded from JSON if available)
TF_CONFIGS = {
    "1h": dict(
        bar_minutes=60,
        ema_fast=9, ema_mid=21, ema_slow=50, ema_regime=200,
        rsi_period=14, atr_period=14, vol_ma_period=20,
        breakout_lookback=20, max_hold_bars=96, cooldown_bars=5,
        sl_atr_mult={3: 3.0},
        atr_floor_pct=0.015,
        trailing_act_pct=0.03, trailing_dist_pct=0.010,
        rsi_entry_min=50.0, rsi_entry_max=80.0, volume_mult=1.5,
    ),
    "15m": dict(
        bar_minutes=15,
        ema_fast=36, ema_mid=84, ema_slow=200, ema_regime=800,
        rsi_period=56, atr_period=56, vol_ma_period=80,
        breakout_lookback=80, max_hold_bars=384, cooldown_bars=20,
        sl_atr_mult={3: 4.0},
        atr_floor_pct=0.020,
        trailing_act_pct=0.03, trailing_dist_pct=0.010,
        rsi_entry_min=60.0, rsi_entry_max=72.0, volume_mult=2.0,
    ),
    "5m": dict(
        bar_minutes=5,
        ema_fast=108, ema_mid=252, ema_slow=600, ema_regime=2400,
        rsi_period=168, atr_period=168, vol_ma_period=240,
        breakout_lookback=240, max_hold_bars=288, cooldown_bars=36,
        sl_atr_mult={3: 5.0},
        # Use best known 5m params (will be updated from sweep if available)
        atr_floor_pct=0.010,
        trailing_act_pct=0.025, trailing_dist_pct=0.010,
        rsi_entry_min=55.0, rsi_entry_max=75.0, volume_mult=2.0,
    ),
}

SCREEN_START_YEAR = 2022
WF_TRAIN_START_YEAR = 2021


def _to_date(value):
    return datetime.fromisoformat(str(value)).date()


def _last_completed_year(latest_date):
    if latest_date.month == 12 and latest_date.day == 31:
        return latest_date.year
    return latest_date.year - 1


def build_screen_windows(latest_date):
    last_full_year = _last_completed_year(latest_date)
    return [
        (f"{year}-01-01", f"{year}-12-31")
        for year in range(SCREEN_START_YEAR, last_full_year + 1)
    ]


def build_wf_windows(latest_date):
    last_full_year = _last_completed_year(latest_date)
    windows = []
    for train_year in range(WF_TRAIN_START_YEAR, last_full_year + 1):
        test_year = train_year + 1
        test_start = date(test_year, 1, 1)
        if latest_date < test_start:
            break
        test_end = min(date(test_year, 6, 30), latest_date)
        windows.append((
            f"{train_year}-01-01",
            f"{train_year}-12-31",
            test_start.isoformat(),
            test_end.isoformat(),
        ))
    return windows


def build_trend_arrays(prepared_data):
    """Build per-symbol {sym: (unix_seconds_array, trend_bool_array)} for fast lookup."""
    arrays = {}
    for sym, data in prepared_data["symbols"].items():
        da = data["da"]
        ts_sec = da.astype("datetime64[s]").astype(np.int64)
        arrays[sym] = (ts_sec, np.asarray(data["trend_up"], dtype=bool))
    return arrays


def run_mtf_backtest(cfg_5m_dict, prepared_5m, trend_1h, trend_15m,
                     start_date=None, end_date=None):
    """
    Run a 5m backtest with multi-timeframe trend filter (vectorized).

    Strategy: Only allow 5m entry if BOTH 1h and 15m show trend_up=True
    at the corresponding timestamps.
    """
    sliced = Backtester.slice_prepared(prepared_5m, start_date, end_date)
    if "error" in sliced:
        return {"error": sliced["error"]}

    filtered = {
        "symbols": {},
        "btc_regime": sliced["btc_regime"],
        "timeline": sliced["timeline"],
    }

    for sym, data in sliced["symbols"].items():
        new_data = {k: v.copy() if hasattr(v, 'copy') else v for k, v in data.items()}
        new_trend = new_data["trend_up"].copy()

        ts_5m = new_data["da"].astype("datetime64[s]").astype(np.int64)

        # Check 1h alignment: floor 5m timestamps to 1h boundary
        if sym in trend_1h:
            ht_ts, ht_trend = trend_1h[sym]
            floored = (ts_5m // 3600) * 3600
            idx = np.searchsorted(ht_ts, floored, side="right") - 1
            idx = np.clip(idx, 0, max(len(ht_ts) - 1, 0))
            match_1h = (ht_ts[idx] == floored) & ht_trend[idx]
        else:
            match_1h = np.zeros(len(ts_5m), dtype=bool)

        # Check 15m alignment: floor 5m timestamps to 15m boundary
        if sym in trend_15m:
            ht_ts, ht_trend = trend_15m[sym]
            floored = (ts_5m // 900) * 900
            idx = np.searchsorted(ht_ts, floored, side="right") - 1
            idx = np.clip(idx, 0, max(len(ht_ts) - 1, 0))
            match_15m = (ht_ts[idx] == floored) & ht_trend[idx]
        else:
            match_15m = np.zeros(len(ts_5m), dtype=bool)

        new_trend &= match_1h & match_15m
        new_data["trend_up"] = new_trend
        filtered["symbols"][sym] = new_data

    bt = Backtester(BacktestConfig(**cfg_5m_dict))
    return bt.run_prepared(filtered)


def extract(result):
    if "error" in result:
        return dict(ret=-100, trades=0, wr=0, dd=100, pf=0, sharpe=None)
    pf_raw = result.get("profit_factor", 0)
    pf_val = 10.0 if isinstance(pf_raw, str) else float(pf_raw)
    return dict(
        ret=result.get("return_pct", -100),
        trades=result.get("total_trades", 0),
        wr=result.get("win_rate", 0),
        dd=result.get("max_drawdown_pct", 100),
        pf=pf_val,
        sharpe=result.get("sharpe_ratio"),
    )


def fmt(v):
    if v is None:
        return "  N/A"
    return f"{v:>6.2f}"


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load best 5m config from sweep if available
    sweep_5m = OUT_DIR / "sweep_5m.json"
    if sweep_5m.exists():
        with open(sweep_5m, "r") as f:
            data = json.load(f)
        best_5m_cfg = data.get("best_config", {})
        # Merge sweep results into TF_CONFIGS
        for k in ["atr_floor_pct", "trailing_act_pct", "trailing_dist_pct",
                   "rsi_entry_min", "rsi_entry_max", "volume_mult"]:
            if k in best_5m_cfg:
                TF_CONFIGS["5m"][k] = best_5m_cfg[k]
        print(f"  Loaded 5m config from sweep: atr={TF_CONFIGS['5m']['atr_floor_pct']}, "
              f"trail={TF_CONFIGS['5m']['trailing_act_pct']}/{TF_CONFIGS['5m']['trailing_dist_pct']}")

    print(f"\n{'='*80}")
    print(f"  MULTI-TIMEFRAME BACKTEST (1h + 15m + 5m Trend Alignment)")
    print(f"{'='*80}")

    # ── Step 1: Load and compute for higher TFs (1h, 15m) ──
    print(f"\n  Loading 1h data for trend lookup...")
    cfg_1h = {**COMMON, **TF_CONFIGS["1h"]}
    bt_1h = Backtester(BacktestConfig(**cfg_1h))
    prepared_1h = bt_1h.prepare_data("data/history/1h")
    t_1h = time.time() - t0
    print(f"    1h loaded in {t_1h:.0f}s ({len(prepared_1h.get('symbols', {}))} symbols)")
    del bt_1h

    print(f"  Loading 15m data for trend lookup...")
    cfg_15m = {**COMMON, **TF_CONFIGS["15m"]}
    bt_15m = Backtester(BacktestConfig(**cfg_15m))
    prepared_15m = bt_15m.prepare_data("data/history/15m")
    t_15m = time.time() - t0
    print(f"    15m loaded in {t_15m - t_1h:.0f}s ({len(prepared_15m.get('symbols', {}))} symbols)")
    del bt_15m

    # Build trend lookups (vectorized — per-symbol numpy arrays)
    print(f"  Building 1h trend arrays...")
    trend_1h = build_trend_arrays(prepared_1h)
    print(f"    {len(trend_1h)} symbols")
    del prepared_1h
    gc.collect()

    print(f"  Building 15m trend arrays...")
    trend_15m = build_trend_arrays(prepared_15m)
    print(f"    {len(trend_15m)} symbols")
    del prepared_15m
    gc.collect()

    # ── Step 2: Load 5m data ──
    print(f"\n  Loading 5m data for simulation...")
    cfg_5m = {**COMMON, **TF_CONFIGS["5m"],
              "momentum_ranking": False, "rr_mode": "trailing", "reentry_enabled": False}
    bt_5m = Backtester(BacktestConfig(**cfg_5m))
    prepared_5m = bt_5m.prepare_data("data/history/5m")
    t_5m = time.time() - t0
    print(f"    5m loaded in {t_5m - t_15m:.0f}s ({len(prepared_5m.get('symbols', {}))} symbols)")
    del bt_5m

    if "error" in prepared_5m:
        print(f"  ERROR: {prepared_5m['error']}")
        return

    data_start = _to_date(prepared_5m["timeline"][0])
    data_end = _to_date(prepared_5m["timeline"][-1])
    screen_windows = build_screen_windows(data_end)
    wf_windows = build_wf_windows(data_end)
    print(f"  Data period: {data_start.isoformat()} ~ {data_end.isoformat()}")
    print(f"  Screening windows: {', '.join(f'{s}~{e}' for s, e in screen_windows)}")
    print(f"  WF windows: {', '.join(f'{tr_s}~{tr_e}->{te_s}~{te_e}' for tr_s, tr_e, te_s, te_e in wf_windows)}")

    # ── Step 3: Screening on multiple windows ──
    print(f"\n  --- SCREENING: {len(screen_windows)}-window validation ---")
    pfs, rets, trades_all = [], [], []
    for s, e in screen_windows:
        raw = run_mtf_backtest(cfg_5m, prepared_5m, trend_1h, trend_15m, s, e)
        m = extract(raw)
        pfs.append(m["pf"])
        rets.append(m["ret"])
        trades_all.append(m["trades"])
        print(f"    {s}~{e}: PF={m['pf']:.3f} ret={m['ret']:+.1f}% trades={m['trades']} wr={m['wr']:.0f}%")

    avg_pf = round(sum(pfs) / len(pfs), 3)
    avg_ret = round(sum(rets) / len(rets), 1)
    avg_trades = round(sum(trades_all) / len(trades_all))
    print(f"\n  Screening: avgPF={avg_pf:.3f} avgRet={avg_ret:+.1f}% avgTrades={avg_trades}")

    # Also run baseline 5m WITHOUT MTF filter for comparison
    print(f"\n  --- BASELINE: 5m only (no MTF filter) ---")
    pfs_base, rets_base = [], []
    for s, e in screen_windows:
        sl = Backtester.slice_prepared(prepared_5m, s, e)
        bt = Backtester(BacktestConfig(**cfg_5m))
        raw = bt.run_prepared(sl)
        m = extract(raw)
        pfs_base.append(m["pf"])
        rets_base.append(m["ret"])
        print(f"    {s}~{e}: PF={m['pf']:.3f} ret={m['ret']:+.1f}% trades={m['trades']}")
        del sl

    avg_pf_base = round(sum(pfs_base) / len(pfs_base), 3)
    avg_ret_base = round(sum(rets_base) / len(rets_base), 1)
    print(f"  Baseline: avgPF={avg_pf_base:.3f} avgRet={avg_ret_base:+.1f}%")
    improvement = avg_pf - avg_pf_base
    print(f"  MTF improvement: {improvement:+.3f} PF")

    # ── Step 4: Walk-Forward Validation ──
    print(f"\n  --- WALK-FORWARD VALIDATION ---")
    wf_results = []
    test_rets, test_pfs = [], []
    for i, (tr_s, tr_e, te_s, te_e) in enumerate(wf_windows, 1):
        # Train window (MTF)
        train_raw = run_mtf_backtest(cfg_5m, prepared_5m, trend_1h, trend_15m, tr_s, tr_e)
        train_m = extract(train_raw)

        # Test window (MTF)
        test_raw = run_mtf_backtest(cfg_5m, prepared_5m, trend_1h, trend_15m, te_s, te_e)
        test_m = extract(test_raw)

        test_rets.append(test_m["ret"])
        test_pfs.append(test_m["pf"])

        wf_results.append({
            "window": f"WF{i}",
            "train_period": f"{tr_s}~{tr_e}",
            "test_period": f"{te_s}~{te_e}",
            "train": train_m,
            "test": test_m,
        })
        print(f"    WF{i} TRAIN {train_m['ret']:>+7.1f}%  TEST {test_m['ret']:>+7.1f}%  "
              f"PF={fmt(test_m['pf'])}  WR={test_m['wr']:.0f}%  trades={test_m['trades']}")

    avg_wf_ret = round(sum(test_rets) / len(test_rets), 2)
    avg_wf_pf = round(sum(test_pfs) / len(test_pfs), 3)
    oos_profitable = sum(1 for r in test_rets if r > 0)

    print(f"\n    Avg OOS return: {avg_wf_ret:+.1f}%  PF: {avg_wf_pf:.2f}")
    print(f"    OOS profitable: {oos_profitable}/{len(test_rets)} windows")

    total_time = time.time() - t0
    print(f"\n  Total MTF time: {total_time:.0f}s ({total_time/60:.1f}m)")

    # Save results
    summary = {
        "timeframe": "mtf_1h_15m_5m",
        "best_config": cfg_5m,
        "config_label": "MTF 1h+15m+5m trend alignment",
        "data_period": {
            "start": data_start.isoformat(),
            "end": data_end.isoformat(),
        },
        "screen_windows_used": screen_windows,
        "wf_windows_used": wf_windows,
        "screening": {
            "avg_pf": avg_pf,
            "avg_ret": avg_ret,
            "avg_trades": avg_trades,
            "pfs": pfs,
            "rets": rets,
        },
        "baseline": {
            "avg_pf": avg_pf_base,
            "avg_ret": avg_ret_base,
        },
        "walkforward": {
            "results": wf_results,
            "avg_test_ret": avg_wf_ret,
            "avg_test_pf": avg_wf_pf,
            "oos_profitable": oos_profitable,
            "oos_total": len(test_rets),
        },
        "total_time_s": round(total_time, 1),
    }

    out_file = OUT_DIR / "sweep_mtf.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"  -> Saved to {out_file}")

    del prepared_5m
    gc.collect()
    return summary


if __name__ == "__main__":
    main()
