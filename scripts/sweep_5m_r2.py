"""
scripts/sweep_5m_r2.py – Round 2: focused sweep around best R1 config
with new noise-filtering params (breakout_margin, min_entry_score, atr_floor_pct).
Also validates on 2021-H1 bull market.

Usage:
    python -m scripts.sweep_5m_r2
"""
import sys, time, json
from pathlib import Path
from core.backtester import Backtester, BacktestConfig

DATA_DIR = "data/history/5m"
OUT_DIR  = Path("logs/sweep_5m")

# ── common base ─────────────────────────────────────────────────────────────
BASE = dict(
    initial_capital=500.0,
    max_positions=5,
    fixed_leverage=3,
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

# ── 12x indicator profile ──────────────────────────────────────────────────
IND_12X = dict(
    ema_fast=108, ema_mid=252, ema_slow=600, ema_regime=2400,
    rsi_period=168, atr_period=168, vol_ma_period=240,
    breakout_lookback=240,
)

# ── aggr_combo baseline (best from R1) ──────────────────────────────────────
AGGR_BASE = dict(
    trailing_act_pct=0.025,
    trailing_dist_pct=0.01,
    sl_atr_mult={3: 5.0},
    max_hold_bars=288,
    rsi_exit_max=78,
    cooldown_bars=36,
    volume_mult=2.0,
)


def make(tag, **overrides):
    kw = {**BASE, **IND_12X, **AGGR_BASE, **overrides, "verbose": False}
    return tag, BacktestConfig(**kw)


# ── scenarios ───────────────────────────────────────────────────────────────
SCENARIOS = [
    # 1. R1 best reference
    make("ref_aggr_combo"),
    # 2–4. Breakout margin (require close > prev_hi * (1+margin))
    make("bkm_0.3pct",    breakout_margin=0.003),
    make("bkm_0.5pct",    breakout_margin=0.005),
    make("bkm_1.0pct",    breakout_margin=0.010),
    # 5–7. Minimum entry score
    make("score_0.15",     min_entry_score=0.15),
    make("score_0.25",     min_entry_score=0.25),
    make("score_0.35",     min_entry_score=0.35),
    # 8–10. ATR floor (skip low-vol entries)
    make("atrfl_0.2pct",   atr_floor_pct=0.002),
    make("atrfl_0.4pct",   atr_floor_pct=0.004),
    make("atrfl_0.6pct",   atr_floor_pct=0.006),
    # 11–13. High volume mult
    make("vol_3.0",        volume_mult=3.0),
    make("vol_4.0",        volume_mult=4.0),
    make("vol_5.0",        volume_mult=5.0),
    # 14–16. Combined: breakout_margin + score + vol
    make("combo_mild",     breakout_margin=0.003, min_entry_score=0.15,
         volume_mult=2.5),
    make("combo_med",      breakout_margin=0.005, min_entry_score=0.25,
         volume_mult=3.0, atr_floor_pct=0.002),
    make("combo_strict",   breakout_margin=0.010, min_entry_score=0.30,
         volume_mult=4.0, atr_floor_pct=0.004),
    # 17–19. Wider stop variants with filters
    make("wide7_bkm",     sl_atr_mult={3: 7.0}, breakout_margin=0.005,
         min_entry_score=0.20),
    make("wide10_strict",  sl_atr_mult={3: 10.0}, breakout_margin=0.010,
         min_entry_score=0.25, volume_mult=3.0),
    # 20–22. Lower leverage with filters
    make("lev2_combo",     fixed_leverage=2, breakout_margin=0.005,
         min_entry_score=0.20, volume_mult=2.5),
    make("lev1_combo",     fixed_leverage=1, breakout_margin=0.005,
         min_entry_score=0.20, volume_mult=2.5),
    # 23–25. Fewer positions
    make("pos3_combo",     max_positions=3, breakout_margin=0.005,
         min_entry_score=0.20, volume_mult=2.5),
    make("pos2_strict",    max_positions=2, breakout_margin=0.010,
         min_entry_score=0.30, volume_mult=4.0),
    # 26–27. RSI entry tightening
    make("rsi_58_75",      rsi_entry_min=58, rsi_entry_max=75,
         breakout_margin=0.005, min_entry_score=0.20),
    make("rsi_60_72",      rsi_entry_min=60, rsi_entry_max=72,
         breakout_margin=0.005, min_entry_score=0.25, volume_mult=3.0),
]


def extract(result):
    if "error" in result:
        return dict(final=0, ret=-100, trades=0, wr=0, dd=100,
                    sharpe=None, calmar=None, pf=0, avg_hold=0,
                    exits={}, err=result["error"])
    return dict(
        final   = result.get("final_capital", 0),
        ret     = result.get("return_pct", -100),
        trades  = result.get("total_trades", 0),
        wr      = result.get("win_rate", 0),
        dd      = result.get("max_drawdown_pct", 100),
        sharpe  = result.get("sharpe_ratio"),
        calmar  = result.get("calmar_ratio"),
        pf      = result.get("profit_factor", 0),
        avg_hold= result.get("avg_hold_bars", 0),
        exits   = result.get("exit_reasons", {}),
        err     = None,
    )


def fmt_num(v):
    if v is None: return "   N/A"
    if isinstance(v, str): return f"{v:>6}"
    return f"{v:>6.2f}"


def run():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── load 12x data ───────────────────────────────────────────────────
    print("=" * 70)
    print("  ROUND 2 — Loading 12x 5m data")
    print("=" * 70)
    ref_cfg = SCENARIOS[0][1]
    bt_load = Backtester(ref_cfg)
    prepared = bt_load.prepare_data(DATA_DIR)
    print(f"  Loaded in {time.time()-t0:.0f}s")
    if "error" in prepared:
        print(f"  ERROR: {prepared['error']}"); return

    # ── WINDOW 1: 2024-H2 sweep ────────────────────────────────────────
    print(f"\n{'='*70}")
    print("  WINDOW 1: 2024-H2  (training)")
    print(f"{'='*70}")
    t1 = time.time()
    sl1 = Backtester.slice_prepared(prepared, "2024-07-01", "2024-12-31")
    print(f"  Sliced → {len(sl1.get('timeline',[]))} bars, "
          f"{len(sl1.get('symbols',{}))} syms  ({time.time()-t1:.0f}s)")

    results_w1 = []
    header = (f"  {'Tag':<22} {'Final':>7} {'Ret%':>7} {'#Tr':>6} "
              f"{'WR%':>5} {'DD%':>6} {'Shrp':>6} {'PF':>6}")
    print(header)
    print(f"  {'-'*70}")

    for tag, cfg in SCENARIOS:
        bt = Backtester(cfg)
        ts = time.time()
        raw = bt.run_prepared(sl1)
        el = time.time() - ts
        m = extract(raw)
        results_w1.append({"tag": tag, "window": "2024-H2", **m, "secs": round(el,1)})
        print(f"  {tag:<22} {m['final']:>7.1f} {m['ret']:>7.1f} {m['trades']:>6} "
              f"{m['wr']:>5.1f} {m['dd']:>6.1f} {fmt_num(m['sharpe'])} "
              f"{fmt_num(m['pf'])} {el:>4.0f}s")

    del sl1

    # ── top-5 from 2024-H2 ─────────────────────────────────────────────
    ranked = sorted(results_w1, key=lambda x: x["ret"], reverse=True)
    top5_tags = [r["tag"] for r in ranked[:5]]
    print(f"\n  Top-5 tags for bull-market validation: {top5_tags}")

    # ── WINDOW 2: 2021-H1 bull test ────────────────────────────────────
    print(f"\n{'='*70}")
    print("  WINDOW 2: 2021-H1  (bull-market validation)")
    print(f"{'='*70}")
    t2 = time.time()
    sl2 = Backtester.slice_prepared(prepared, "2021-01-01", "2021-06-30")
    print(f"  Sliced → {len(sl2.get('timeline',[]))} bars, "
          f"{len(sl2.get('symbols',{}))} syms  ({time.time()-t2:.0f}s)")

    results_w2 = []
    top5_scenarios = [(t, c) for t, c in SCENARIOS if t in top5_tags]
    # also add reference
    if "ref_aggr_combo" not in top5_tags:
        top5_scenarios.insert(0, SCENARIOS[0])

    print(header)
    print(f"  {'-'*70}")
    for tag, cfg in top5_scenarios:
        bt = Backtester(cfg)
        ts = time.time()
        raw = bt.run_prepared(sl2)
        el = time.time() - ts
        m = extract(raw)
        results_w2.append({"tag": tag, "window": "2021-H1", **m, "secs": round(el,1)})
        print(f"  {tag:<22} {m['final']:>7.1f} {m['ret']:>7.1f} {m['trades']:>6} "
              f"{m['wr']:>5.1f} {m['dd']:>6.1f} {fmt_num(m['sharpe'])} "
              f"{fmt_num(m['pf'])} {el:>4.0f}s")

    del sl2

    # ── WINDOW 3: 2023-H2 (recovery market) ────────────────────────────
    print(f"\n{'='*70}")
    print("  WINDOW 3: 2023-H2  (recovery validation)")
    print(f"{'='*70}")
    t3 = time.time()
    sl3 = Backtester.slice_prepared(prepared, "2023-07-01", "2023-12-31")
    print(f"  Sliced → {len(sl3.get('timeline',[]))} bars, "
          f"{len(sl3.get('symbols',{}))} syms  ({time.time()-t3:.0f}s)")

    results_w3 = []
    print(header)
    print(f"  {'-'*70}")
    for tag, cfg in top5_scenarios:
        bt = Backtester(cfg)
        ts = time.time()
        raw = bt.run_prepared(sl3)
        el = time.time() - ts
        m = extract(raw)
        results_w3.append({"tag": tag, "window": "2023-H2", **m, "secs": round(el,1)})
        print(f"  {tag:<22} {m['final']:>7.1f} {m['ret']:>7.1f} {m['trades']:>6} "
              f"{m['wr']:>5.1f} {m['dd']:>6.1f} {fmt_num(m['sharpe'])} "
              f"{fmt_num(m['pf'])} {el:>4.0f}s")

    del sl3, prepared

    # ── final summary ───────────────────────────────────────────────────
    total = time.time() - t0
    all_results = results_w1 + results_w2 + results_w3
    print(f"\n{'='*70}")
    print(f"  R2 COMPLETE — {len(all_results)} runs in {total:.0f}s ({total/60:.1f}m)")
    print(f"{'='*70}")

    # Cross-window comparison for top-5
    print(f"\n  CROSS-WINDOW COMPARISON (top-5 from 2024-H2):")
    print(f"  {'Tag':<22} {'2024-H2':>10} {'2021-H1':>10} {'2023-H2':>10}")
    print(f"  {'-'*55}")
    for tag in top5_tags:
        vals = []
        for rlist in [results_w1, results_w2, results_w3]:
            r = next((x for x in rlist if x["tag"] == tag), None)
            vals.append(f"{r['ret']:>9.1f}%" if r else "      N/A")
        print(f"  {tag:<22} {vals[0]} {vals[1]} {vals[2]}")

    out_file = OUT_DIR / "sweep_r2_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Results → {out_file}")


if __name__ == "__main__":
    run()
