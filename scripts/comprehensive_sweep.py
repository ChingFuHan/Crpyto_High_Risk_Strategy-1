"""
Comprehensive multi-timeframe backtest sweep v2.

Phase 1: Parameter search per TF (ATR floor x trailing x RSI grid)
Phase 2: Add momentum/RR/reentry on top of best base
Phase 3: Walk-forward validate top configs
Uses PF as primary screening metric, multiple 1-year windows.
"""
import sys, time, json, gc
from datetime import date, datetime
from pathlib import Path
from core.backtester import Backtester, BacktestConfig

OUT_DIR = Path("logs/comprehensive_sweep")

# Bar-count params scale with timeframe; price-% params are SEARCHED
TIMEFRAME_PARAMS = {
    "1h": dict(
        data_dir="data/history/1h", bar_minutes=60,
        ema_fast=9, ema_mid=21, ema_slow=50, ema_regime=200,
        rsi_period=14, atr_period=14, vol_ma_period=20,
        breakout_lookback=20, max_hold_bars=96, cooldown_bars=5,
        sl_atr_mult={3: 3.0},
    ),
    "15m": dict(
        data_dir="data/history/15m", bar_minutes=15,
        ema_fast=36, ema_mid=84, ema_slow=200, ema_regime=800,
        rsi_period=56, atr_period=56, vol_ma_period=80,
        breakout_lookback=80, max_hold_bars=384, cooldown_bars=20,
        sl_atr_mult={3: 4.0},
    ),
    "5m": dict(
        data_dir="data/history/5m", bar_minutes=5,
        ema_fast=108, ema_mid=252, ema_slow=600, ema_regime=2400,
        rsi_period=168, atr_period=168, vol_ma_period=240,
        breakout_lookback=240, max_hold_bars=288, cooldown_bars=36,
        sl_atr_mult={3: 5.0},
    ),
}

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

SCREEN_START_YEAR = 2022
WF_TRAIN_START_YEAR = 2021

ATR_FLOORS = [0.0, 0.005, 0.008, 0.010, 0.012, 0.015, 0.020]
MIN_TRADES_PER_YEAR = 30  # Minimum trades for statistical significance
TRAIL_COMBOS = [
    (0.025, 0.010),
    (0.040, 0.015),
    (0.060, 0.025),
    (0.100, 0.040),
    (0.150, 0.060),
    (0.200, 0.080),
]
RSI_RANGES = [
    (50.0, 80.0),
    (55.0, 75.0),
    (60.0, 72.0),
]
VOL_MULTS = [1.5, 2.0, 3.0]

MOMENTUM_LOOKBACKS = [8.0, 12.0, 24.0]
RR_MODES = ["trailing", "1:1", "1:2", "1:3"]


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


def extract(result):
    if "error" in result:
        return dict(ret=-100, trades=0, wr=0, dd=100, pf=0, sharpe=None)
    pf_raw = result.get("profit_factor", 0)
    pf_val = 10.0 if isinstance(pf_raw, str) else float(pf_raw)
    return dict(
        ret    = result.get("return_pct", -100),
        trades = result.get("total_trades", 0),
        wr     = result.get("win_rate", 0),
        dd     = result.get("max_drawdown_pct", 100),
        pf     = pf_val,
        sharpe = result.get("sharpe_ratio"),
    )


def screen_multi(cfg_dict, prepared, windows):
    """Screen on multiple 1-year windows; return avg PF and avg return."""
    if not windows:
        return {
            "avg_pf": 0.0,
            "avg_ret": -100.0,
            "avg_trades": 0,
            "pfs": [],
            "rets": [],
            "min_pf": 0.0,
            "quality": 0.0,
        }
    pfs, rets, trades_all = [], [], []
    for s, e in windows:
        bt = Backtester(BacktestConfig(**cfg_dict))
        sl = Backtester.slice_prepared(prepared, s, e)
        raw = bt.run_prepared(sl)
        m = extract(raw)
        pfs.append(m["pf"])
        rets.append(m["ret"])
        trades_all.append(m["trades"])
        del sl
    avg_pf = round(sum(pfs) / len(pfs), 3)
    avg_trades = round(sum(trades_all) / len(trades_all))
    # Quality score: PF penalized if trades < MIN_TRADES_PER_YEAR
    trade_penalty = min(1.0, avg_trades / MIN_TRADES_PER_YEAR) if avg_trades < MIN_TRADES_PER_YEAR else 1.0
    quality = round(avg_pf * trade_penalty, 3)
    return {
        "avg_pf": avg_pf,
        "avg_ret": round(sum(rets) / len(rets), 1),
        "avg_trades": avg_trades,
        "pfs": pfs,
        "rets": rets,
        "min_pf": min(pfs),
        "quality": quality,
    }


def walkforward(cfg_dict, prepared, windows):
    if not windows:
        return {
            "results": [],
            "avg_test_ret": -100.0,
            "avg_test_pf": 0.0,
            "oos_profitable": 0,
            "oos_total": 0,
        }
    results = []
    for i, (tr_s, tr_e, te_s, te_e) in enumerate(windows, 1):
        sl_train = Backtester.slice_prepared(prepared, tr_s, tr_e)
        bt = Backtester(BacktestConfig(**cfg_dict))
        raw = bt.run_prepared(sl_train)
        train_m = extract(raw)
        del sl_train

        sl_test = Backtester.slice_prepared(prepared, te_s, te_e)
        bt2 = Backtester(BacktestConfig(**cfg_dict))
        raw = bt2.run_prepared(sl_test)
        test_m = extract(raw)
        del sl_test

        results.append({
            "window": f"WF{i}", "train": train_m, "test": test_m,
            "train_period": f"{tr_s}~{tr_e}", "test_period": f"{te_s}~{te_e}",
        })

    test_rets = [r["test"]["ret"] for r in results]
    test_pfs = [r["test"]["pf"] for r in results if isinstance(r["test"]["pf"], (int, float))]
    return {
        "results": results,
        "avg_test_ret": round(sum(test_rets) / len(test_rets), 2),
        "avg_test_pf": round(sum(test_pfs) / max(len(test_pfs), 1), 3),
        "oos_profitable": sum(1 for r in test_rets if r > 0),
        "oos_total": len(test_rets),
    }


def fmt(v):
    if v is None: return "  N/A"
    return f"{v:>6.2f}"


def run_timeframe(tf_name):
    t0 = time.time()
    tf = TIMEFRAME_PARAMS[tf_name]
    data_dir = tf["data_dir"]

    print(f"\n{'='*80}")
    print(f"  TIMEFRAME: {tf_name}")
    print(f"{'='*80}")

    base = {**COMMON, **{k: v for k, v in tf.items() if k != "data_dir"}}

    print(f"  Loading {data_dir} ...")
    bt_load = Backtester(BacktestConfig(**{**base,
        "atr_floor_pct": 0.01, "trailing_act_pct": 0.06,
        "trailing_dist_pct": 0.025, "rsi_entry_min": 55, "rsi_entry_max": 75,
        "volume_mult": 2.0}))
    prepared = bt_load.prepare_data(data_dir)
    print(f"  Data loaded in {time.time()-t0:.0f}s")
    if "error" in prepared:
        print(f"  ERROR: {prepared['error']}")
        return None
    del bt_load

    data_start = _to_date(prepared["timeline"][0])
    data_end = _to_date(prepared["timeline"][-1])
    screen_windows = build_screen_windows(data_end)
    wf_windows = build_wf_windows(data_end)

    # For 5m, use the latest completed screening year in Phase 1 to cut time.
    fast_mode = (tf_name == "5m" and bool(screen_windows))
    phase1_windows = [screen_windows[-1]] if fast_mode else screen_windows
    if fast_mode:
        print(f"  Phase 1 fast mode window: {phase1_windows[0][0]}~{phase1_windows[0][1]}")
    print(f"  Data period: {data_start.isoformat()} ~ {data_end.isoformat()}")
    print(f"  Screening windows: {', '.join(f'{s}~{e}' for s, e in screen_windows)}")
    print(f"  WF windows: {', '.join(f'{tr_s}~{tr_e}->{te_s}~{te_e}' for tr_s, tr_e, te_s, te_e in wf_windows)}")

    all_results = {}
    scr = lambda cfg: screen_multi(cfg, prepared, windows=phase1_windows)

    # PHASE 1: Greedy parameter search
    print(f"\n  --- PHASE 1: Base Parameter Search ---")

    # 1a: ATR floor
    print(f"\n  [1a] ATR floor sweep")
    best_atr, best_atr_q = 0.01, 0
    for af in ATR_FLOORS:
        cfg = {**base, "atr_floor_pct": af,
               "trailing_act_pct": 0.06, "trailing_dist_pct": 0.025,
               "rsi_entry_min": 55.0, "rsi_entry_max": 75.0, "volume_mult": 2.0,
               "momentum_ranking": False, "rr_mode": "trailing", "reentry_enabled": False}
        s = scr(cfg)
        print(f"    atr={af:.3f}: PF={s['avg_pf']:.3f} Q={s['quality']:.3f} ret={s['avg_ret']:>+6.1f}% "
              f"trades={s['avg_trades']}")
        if s['quality'] > best_atr_q:
            best_atr_q = s['quality']
            best_atr = af
    print(f"    -> Best ATR floor: {best_atr:.3f} (Q={best_atr_q:.3f})")

    # 1b: Trailing stop
    print(f"\n  [1b] Trailing stop sweep")
    best_trail, best_trail_q = (0.06, 0.025), 0
    for ta, td in TRAIL_COMBOS:
        cfg = {**base, "atr_floor_pct": best_atr,
               "trailing_act_pct": ta, "trailing_dist_pct": td,
               "rsi_entry_min": 55.0, "rsi_entry_max": 75.0, "volume_mult": 2.0,
               "momentum_ranking": False, "rr_mode": "trailing", "reentry_enabled": False}
        s = scr(cfg)
        print(f"    trail={ta:.2f}/{td:.3f}: PF={s['avg_pf']:.3f} Q={s['quality']:.3f} ret={s['avg_ret']:>+6.1f}% "
              f"trades={s['avg_trades']}")
        if s['quality'] > best_trail_q:
            best_trail_q = s['quality']
            best_trail = (ta, td)
    print(f"    -> Best trailing: {best_trail[0]:.2f}/{best_trail[1]:.3f} (Q={best_trail_q:.3f})")

    # 1c: RSI range
    print(f"\n  [1c] RSI range sweep")
    best_rsi, best_rsi_q = (55.0, 75.0), 0
    for rmin, rmax in RSI_RANGES:
        cfg = {**base, "atr_floor_pct": best_atr,
               "trailing_act_pct": best_trail[0], "trailing_dist_pct": best_trail[1],
               "rsi_entry_min": rmin, "rsi_entry_max": rmax, "volume_mult": 2.0,
               "momentum_ranking": False, "rr_mode": "trailing", "reentry_enabled": False}
        s = scr(cfg)
        print(f"    rsi={rmin:.0f}-{rmax:.0f}: PF={s['avg_pf']:.3f} Q={s['quality']:.3f} ret={s['avg_ret']:>+6.1f}% "
              f"trades={s['avg_trades']}")
        if s['quality'] > best_rsi_q:
            best_rsi_q = s['quality']
            best_rsi = (rmin, rmax)
    print(f"    -> Best RSI: {best_rsi[0]:.0f}-{best_rsi[1]:.0f} (Q={best_rsi_q:.3f})")

    # 1d: Volume multiplier
    print(f"\n  [1d] Volume multiplier sweep")
    best_vol, best_vol_q = 2.0, 0
    for vm in VOL_MULTS:
        cfg = {**base, "atr_floor_pct": best_atr,
               "trailing_act_pct": best_trail[0], "trailing_dist_pct": best_trail[1],
               "rsi_entry_min": best_rsi[0], "rsi_entry_max": best_rsi[1],
               "volume_mult": vm,
               "momentum_ranking": False, "rr_mode": "trailing", "reentry_enabled": False}
        s = scr(cfg)
        print(f"    vol={vm:.1f}: PF={s['avg_pf']:.3f} Q={s['quality']:.3f} ret={s['avg_ret']:>+6.1f}% "
              f"trades={s['avg_trades']}")
        if s['quality'] > best_vol_q:
            best_vol_q = s['quality']
            best_vol = vm
    print(f"    -> Best volume: {best_vol:.1f} (Q={best_vol_q:.3f})")

    best_base = {**base,
        "atr_floor_pct": best_atr,
        "trailing_act_pct": best_trail[0], "trailing_dist_pct": best_trail[1],
        "rsi_entry_min": best_rsi[0], "rsi_entry_max": best_rsi[1],
        "volume_mult": best_vol,
        "momentum_ranking": False, "rr_mode": "trailing", "reentry_enabled": False,
    }
    # Full 3-window confirmation of best base
    s = screen_multi(best_base, prepared, windows=screen_windows)
    print(f"\n  * Best base ({len(screen_windows)}-window): avgPF={s['avg_pf']:.3f} Q={s['quality']:.3f} ret={s['avg_ret']:>+6.1f}% trades={s['avg_trades']}")
    all_results["base_best"] = {**best_base, **s}

    # PHASE 2: Features
    print(f"\n  --- PHASE 2: Feature Optimization ---")

    # 2a: Momentum
    print(f"\n  [2a] Momentum ranking")
    best_mom_cfg = {**best_base}
    best_mom_q = s['quality']
    for hours in MOMENTUM_LOOKBACKS:
        cfg = {**best_base, "momentum_ranking": True, "momentum_lookback_hours": hours}
        sm = screen_multi(cfg, prepared, windows=screen_windows)
        tag = f"mom_{int(hours)}h"
        print(f"    {tag}: PF={sm['avg_pf']:.3f} Q={sm['quality']:.3f} ret={sm['avg_ret']:>+6.1f}% trades={sm['avg_trades']}")
        all_results[tag] = {**cfg, **sm}
        if sm['quality'] > best_mom_q:
            best_mom_q = sm['quality']
            best_mom_cfg = cfg.copy()
    print(f"    -> Best momentum Q={best_mom_q:.3f}")

    # 2b: RR modes
    print(f"\n  [2b] Risk-Reward modes")
    best_rr_cfg = {**best_mom_cfg}
    best_rr_q = best_mom_q
    for rr in RR_MODES:
        cfg = {**best_mom_cfg, "rr_mode": rr}
        sm = screen_multi(cfg, prepared, windows=screen_windows)
        tag = f"rr_{rr.replace(':', '')}"
        print(f"    {tag}: PF={sm['avg_pf']:.3f} Q={sm['quality']:.3f} ret={sm['avg_ret']:>+6.1f}% trades={sm['avg_trades']}")
        all_results[tag] = {**cfg, **sm}
        if sm['quality'] > best_rr_q:
            best_rr_q = sm['quality']
            best_rr_cfg = cfg.copy()
    print(f"    -> Best RR Q={best_rr_q:.3f}")

    # 2c: Reentry
    print(f"\n  [2c] Re-entry mechanism")
    best_final_cfg = {**best_rr_cfg, "reentry_enabled": False}
    best_final_q = best_rr_q
    for reentry in [False, True]:
        cfg = {**best_rr_cfg, "reentry_enabled": reentry}
        sm = screen_multi(cfg, prepared, windows=screen_windows)
        tag = f"reentry_{'on' if reentry else 'off'}"
        print(f"    {tag}: PF={sm['avg_pf']:.3f} Q={sm['quality']:.3f} ret={sm['avg_ret']:>+6.1f}% trades={sm['avg_trades']}")
        all_results[tag] = {**cfg, **sm}
        if sm['quality'] > best_final_q:
            best_final_q = sm['quality']
            best_final_cfg = cfg.copy()

    s = screen_multi(best_final_cfg, prepared, windows=screen_windows)
    print(f"\n  * Final best: PF={s['avg_pf']:.3f} Q={s['quality']:.3f} ret={s['avg_ret']:>+6.1f}% trades={s['avg_trades']}")

    # PHASE 3: Walk-forward
    print(f"\n  --- PHASE 3: Walk-Forward Validation ---")
    wf = walkforward(best_final_cfg, prepared, windows=wf_windows)
    print(f"    Avg OOS return: {wf['avg_test_ret']:+.1f}%  PF: {wf['avg_test_pf']:.2f}")
    print(f"    OOS profitable: {wf['oos_profitable']}/{wf['oos_total']} windows")
    for r in wf["results"]:
        tm, te = r["train"], r["test"]
        print(f"    {r['window']} TRAIN {tm['ret']:>+7.1f}%  TEST {te['ret']:>+7.1f}%  "
              f"PF={fmt(te['pf'])}  WR={te['wr']:.0f}%  trades={te['trades']}")

    total_time = time.time() - t0
    print(f"\n  Total time for {tf_name}: {total_time:.0f}s ({total_time/60:.1f}m)")

    bc = best_final_cfg
    parts = [
        f"atr={bc['atr_floor_pct']:.3f}",
        f"trail={bc['trailing_act_pct']:.2f}/{bc['trailing_dist_pct']:.3f}",
        f"rsi={bc['rsi_entry_min']:.0f}-{bc['rsi_entry_max']:.0f}",
        f"vol={bc['volume_mult']:.1f}",
    ]
    if bc.get("momentum_ranking"):
        parts.append(f"mom{int(bc['momentum_lookback_hours'])}h")
    parts.append(f"rr={bc.get('rr_mode', 'trailing')}")
    if bc.get("reentry_enabled"):
        parts.append("reentry")

    summary = {
        "timeframe": tf_name,
        "best_config": {k: v for k, v in bc.items() if not callable(v)},
        "config_label": " | ".join(parts),
        "data_period": {
            "start": data_start.isoformat(),
            "end": data_end.isoformat(),
        },
        "screen_windows_used": screen_windows,
        "wf_windows_used": wf_windows,
        "screening": s,
        "walkforward": wf,
        "all_results": {k: {kk: vv for kk, vv in v.items() if not callable(vv)}
                        for k, v in all_results.items()},
        "total_time_s": round(total_time, 1),
    }

    del prepared
    gc.collect()
    return summary


def main():
    t_start = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_summaries = {}

    for tf in ["1h", "15m", "5m"]:
        existing = OUT_DIR / f"sweep_{tf}.json"
        if existing.exists():
            print(f"\n  Skipping {tf} — loading cached {existing}")
            with open(existing, "r", encoding="utf-8") as f:
                all_summaries[tf] = json.load(f)
            continue
        summary = run_timeframe(tf)
        if summary:
            all_summaries[tf] = summary
            out_file = OUT_DIR / f"sweep_{tf}.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, default=str)
            print(f"  -> Saved to {out_file}")

    combined_file = OUT_DIR / "all_timeframes.json"
    with open(combined_file, "w", encoding="utf-8") as f:
        json.dump(all_summaries, f, indent=2, default=str)

    total = time.time() - t_start

    print(f"\n{'='*90}")
    print(f"  FINAL COMPARISON - ALL SINGLE TIMEFRAMES (WITH FEES)")
    print(f"{'='*90}")
    print(f"  {'TF':<5} {'Config':<45} {'ScnPF':>6} {'Scn%':>7} {'WF%':>7} {'WFPF':>6} {'Prof':>5}")
    print(f"  {'-'*85}")

    for tf, s in all_summaries.items():
        scn = s["screening"]
        wf = s["walkforward"]
        prof = f"{wf['oos_profitable']}/{wf['oos_total']}"
        print(f"  {tf:<5} {s['config_label']:<45} {scn['avg_pf']:>6.3f} "
              f"{scn['avg_ret']:>+6.1f}% {wf['avg_test_ret']:>+6.1f}% "
              f"{wf['avg_test_pf']:>6.3f} {prof:>5}")

    print(f"\n  Total time: {total:.0f}s ({total/60:.1f}m / {total/3600:.1f}h)")
    print(f"  Results -> {combined_file}")


if __name__ == "__main__":
    main()
