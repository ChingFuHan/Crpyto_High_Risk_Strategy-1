"""
Walk-forward test for atrfl_010 (conservative: high PF, fewer trades).
"""
import sys, time, json
from pathlib import Path
from core.backtester import Backtester, BacktestConfig

DATA_DIR = "data/history/5m"
OUT_DIR  = Path("logs/sweep_5m")

# atrfl_010: higher ATR floor (1.0%) = fewer but high-quality trades
# R3 results: +140.2% / +149.5% / +119.2%, PF 1.43/1.31/1.41, ~300-400 trades/6mo
ATRFL_010_CONFIG = dict(
    initial_capital=500.0,
    max_positions=5,
    fixed_leverage=3,
    fee_rate=0.0008,
    slippage_rate=0.0005,
    funding_rate_worst=0.0002,
    funding_rate_avg=0.0001,
    funding_rate_blend_worst=0.25,
    funding_rate_blend_avg=0.75,
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
    atr_floor_pct=0.010,  # 1.0% (vs 0.6% for trail_20_8)
    trailing_act_pct=0.025,
    trailing_dist_pct=0.01,
    sl_atr_mult={3: 5.0},
    max_hold_bars=288,
    rsi_exit_max=78,
    cooldown_bars=36,
    verbose=False,
)

WALK_FORWARD_WINDOWS = [
    ("2021-01-01", "2021-12-31", "2022-01-01", "2022-06-30"),
    ("2022-01-01", "2022-12-31", "2023-01-01", "2023-06-30"),
    ("2023-01-01", "2023-12-31", "2024-01-01", "2024-06-30"),
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

def run():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = BacktestConfig(**ATRFL_010_CONFIG)

    print("=" * 70)
    print("  WALK-FORWARD VALIDATION — atrfl_010 (Conservative Config)")
    print("=" * 70)
    print(f"  Config: RSI {cfg.rsi_entry_min}-{cfg.rsi_entry_max}, "
          f"ATR floor {cfg.atr_floor_pct}, trail {cfg.trailing_act_pct}/{cfg.trailing_dist_pct}")
    print(f"  Fees: {cfg.fee_rate*100:.2f}% taker, {cfg.slippage_rate*100:.2f}% slippage, "
          f"funding {cfg.funding_rate_avg*100:.3f}% avg + {cfg.funding_rate_worst*100:.3f}% worst (blend {cfg.funding_rate_blend_avg:.0%}/{cfg.funding_rate_blend_worst:.0%})")

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
        ts = time.time()
        sl_train = Backtester.slice_prepared(prepared, tr_s, tr_e)
        bt = Backtester(cfg)
        raw_train = bt.run_prepared(sl_train)
        el = time.time() - ts
        m = extract(raw_train)
        results.append({"window": f"WF{i}", "phase": "TRAIN", "period": f"{tr_s}~{tr_e}", **m})
        print(f"  WF{i:<7} {'TRAIN':<6} {tr_s}~{tr_e:<12} {m['final']:>7.1f} "
              f"{m['ret']:>7.1f} {m['trades']:>5} {m['wr']:>5.1f} {m['dd']:>5.1f} "
              f"{fmt(m['sharpe'])} {fmt(m['pf'])}  {el:.0f}s")
        del sl_train

        ts = time.time()
        sl_test = Backtester.slice_prepared(prepared, te_s, te_e)
        bt2 = Backtester(cfg)
        raw_test = bt2.run_prepared(sl_test)
        el = time.time() - ts
        m = extract(raw_test)
        results.append({"window": f"WF{i}", "phase": "TEST", "period": f"{te_s}~{te_e}", **m})
        print(f"  {'':>9} {'TEST':<6} {te_s}~{te_e:<12} {m['final']:>7.1f} "
              f"{m['ret']:>7.1f} {m['trades']:>5} {m['wr']:>5.1f} {m['dd']:>5.1f} "
              f"{fmt(m['sharpe'])} {fmt(m['pf'])}  {el:.0f}s")
        del sl_test

    del prepared

    total = time.time() - t0
    train_results = [r for r in results if r["phase"] == "TRAIN"]
    test_results  = [r for r in results if r["phase"] == "TEST"]
    avg_train_ret = sum(r["ret"] for r in train_results) / len(train_results)
    avg_test_ret  = sum(r["ret"] for r in test_results) / len(test_results)
    avg_train_pf  = sum(r["pf"] for r in train_results) / len(train_results)
    avg_test_pf   = sum(r["pf"] for r in test_results) / len(test_results)
    oos_positive  = sum(1 for r in test_results if r["ret"] > 0)

    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD SUMMARY (atrfl_010 WITH FEES)")
    print(f"{'='*70}")
    print(f"  Avg TRAIN return: {avg_train_ret:>+7.1f}%  PF: {avg_train_pf:.2f}")
    print(f"  Avg TEST  return: {avg_test_ret:>+7.1f}%  PF: {avg_test_pf:.2f}")
    print(f"  OOS profitable:   {oos_positive}/{len(test_results)} windows")
    print(f"  Total time:       {total:.0f}s ({total/60:.1f}m)")

    out_file = OUT_DIR / "walkforward_atrfl_010_fees.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "config_name": "atrfl_010",
            "config": {k: v for k, v in ATRFL_010_CONFIG.items() if k != "verbose"},
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
