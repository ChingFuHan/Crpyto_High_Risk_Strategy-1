"""
scripts/sweep_5m_r3.py – Round 3: fine-tune around rsi_60_72 (best R2 config)

rsi_60_72 was the ONLY config profitable across ALL 3 windows:
  2024-H2: +5.5%,  PF 1.03
  2021-H1: +12.7%, PF 1.04
  2023-H2: +8.3%,  PF 1.04

Fine-tune: RSI band, trail, SL, positions, hold, cooldown, ATR floor,
then combine best params.

Usage:
    python -m scripts.sweep_5m_r3
"""
import sys, time, json
from pathlib import Path
from core.backtester import Backtester, BacktestConfig

DATA_DIR = "data/history/5m"
OUT_DIR  = Path("logs/sweep_5m")

# ── rsi_60_72 base config (R2 winner) ──────────────────────────────────────
WINNER_BASE = dict(
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
    # indicators (12x)
    ema_fast=108, ema_mid=252, ema_slow=600, ema_regime=2400,
    rsi_period=168, atr_period=168, vol_ma_period=240,
    breakout_lookback=240,
    # entry filters (from R2 rsi_60_72)
    volume_mult=3.0,
    breakout_margin=0.005,
    min_entry_score=0.25,
    atr_floor_pct=0.006,
    # exit (aggr_combo base)
    trailing_act_pct=0.025,
    trailing_dist_pct=0.01,
    sl_atr_mult={3: 5.0},
    max_hold_bars=288,
    rsi_exit_max=78,
    cooldown_bars=36,
)


def make(tag, **overrides):
    kw = {**WINNER_BASE, **overrides, "verbose": False}
    return tag, BacktestConfig(**kw)


# ── scenarios ───────────────────────────────────────────────────────────────
SCENARIOS = [
    # 0. Reference (R2 winner)
    make("ref_rsi6072"),

    # ── RSI band fine-tuning ──
    make("rsi_58_72", rsi_entry_min=58),
    make("rsi_62_72", rsi_entry_min=62),
    make("rsi_60_70", rsi_entry_max=70),
    make("rsi_60_74", rsi_entry_max=74),
    make("rsi_62_70", rsi_entry_min=62, rsi_entry_max=70),
    make("rsi_60_68", rsi_entry_max=68),

    # ── Trail tuning ──
    make("trail_20_8",  trailing_act_pct=0.020, trailing_dist_pct=0.008),
    make("trail_20_10", trailing_act_pct=0.020, trailing_dist_pct=0.010),
    make("trail_30_12", trailing_act_pct=0.030, trailing_dist_pct=0.012),
    make("trail_30_15", trailing_act_pct=0.030, trailing_dist_pct=0.015),
    make("trail_35_15", trailing_act_pct=0.035, trailing_dist_pct=0.015),

    # ── Stop loss width ──
    make("sl_4x",  sl_atr_mult={3: 4.0}),
    make("sl_6x",  sl_atr_mult={3: 6.0}),
    make("sl_7x",  sl_atr_mult={3: 7.0}),
    make("sl_8x",  sl_atr_mult={3: 8.0}),

    # ── Max positions ──
    make("pos2",   max_positions=2),
    make("pos3",   max_positions=3),
    make("pos7",   max_positions=7),

    # ── Max hold bars ──
    make("hold_200", max_hold_bars=200),
    make("hold_400", max_hold_bars=400),
    make("hold_576", max_hold_bars=576),

    # ── Cooldown ──
    make("cd_24",  cooldown_bars=24),
    make("cd_48",  cooldown_bars=48),

    # ── ATR floor ──
    make("atrfl_005", atr_floor_pct=0.005),
    make("atrfl_007", atr_floor_pct=0.007),
    make("atrfl_008", atr_floor_pct=0.008),
    make("atrfl_010", atr_floor_pct=0.010),

    # ── Volume mult ──
    make("vol_2.0", volume_mult=2.0),
    make("vol_4.0", volume_mult=4.0),

    # ── Breakout margin ──
    make("bkm_003", breakout_margin=0.003),
    make("bkm_008", breakout_margin=0.008),
    make("bkm_010", breakout_margin=0.010),

    # ── Equity trail ──
    make("eqtr_20", equity_trail_pct=0.20),
    make("eqtr_30", equity_trail_pct=0.30),
    make("eqtr_off", equity_trail_pct=0.0),
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
    return f"{v:>6.2f}"


def run_window(name, prepared, start, end, scenarios, header):
    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")
    ts = time.time()
    sliced = Backtester.slice_prepared(prepared, start, end)
    print(f"  Sliced → {len(sliced.get('timeline',[]))} bars, "
          f"{len(sliced.get('symbols',{}))} syms  ({time.time()-ts:.0f}s)")
    print(header)
    print(f"  {'-'*74}")

    results = []
    for tag, cfg in scenarios:
        bt = Backtester(cfg)
        t0 = time.time()
        raw = bt.run_prepared(sliced)
        el = time.time() - t0
        m = extract(raw)
        results.append({"tag": tag, "window": name, **m, "secs": round(el,1)})
        print(f"  {tag:<18} {m['final']:>7.1f} {m['ret']:>7.1f} {m['trades']:>5} "
              f"{m['wr']:>5.1f} {m['dd']:>5.1f} {fmt_num(m['sharpe'])} "
              f"{fmt_num(m['pf'])} {el:>4.0f}s")

    del sliced
    return results


def run():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    header = (f"  {'Tag':<18} {'Final':>7} {'Ret%':>7} {'#Tr':>5} "
              f"{'WR%':>5} {'DD%':>5} {'Shrp':>6} {'PF':>6}")

    # ── load data ───────────────────────────────────────────────────────
    print("=" * 70)
    print("  ROUND 3 — Loading 12x 5m data")
    print("=" * 70)
    ref_cfg = SCENARIOS[0][1]
    bt_load = Backtester(ref_cfg)
    prepared = bt_load.prepare_data(DATA_DIR)
    print(f"  Loaded in {time.time()-t0:.0f}s")
    if "error" in prepared:
        print(f"  ERROR: {prepared['error']}"); return

    # ── 3 windows ───────────────────────────────────────────────────────
    windows = [
        ("W1: 2024-H2 (training)", "2024-07-01", "2024-12-31"),
        ("W2: 2021-H1 (bull)",     "2021-01-01", "2021-06-30"),
        ("W3: 2023-H2 (recovery)", "2023-07-01", "2023-12-31"),
    ]

    all_results = []
    window_results = {}
    for wname, ws, we in windows:
        wr = run_window(wname, prepared, ws, we, SCENARIOS, header)
        all_results.extend(wr)
        window_results[wname] = {r["tag"]: r for r in wr}

    del prepared

    # ── cross-window summary ────────────────────────────────────────────
    total = time.time() - t0
    print(f"\n{'='*70}")
    print(f"  R3 COMPLETE — {len(all_results)} runs in {total:.0f}s ({total/60:.1f}m)")
    print(f"{'='*70}")

    # Compute average return & PF across windows
    tags = [t for t, _ in SCENARIOS]
    wnames = [w[0] for w in windows]
    tag_avg = {}
    for tag in tags:
        rets = []
        pfs  = []
        for wn in wnames:
            r = window_results.get(wn, {}).get(tag)
            if r:
                rets.append(r["ret"])
                pfs.append(r["pf"] or 0)
        tag_avg[tag] = {
            "avg_ret": sum(rets)/len(rets) if rets else -100,
            "avg_pf":  sum(pfs)/len(pfs) if pfs else 0,
            "rets": rets,
        }

    ranked = sorted(tag_avg.items(), key=lambda x: x[1]["avg_ret"], reverse=True)

    print(f"\n  CROSS-WINDOW RANKING (by avg return):")
    print(f"  {'Rank':<5} {'Tag':<18} {'Avg%':>7} {'AvgPF':>6}  "
          f"{'W1':>8} {'W2':>8} {'W3':>8}")
    print(f"  {'-'*68}")
    for i, (tag, info) in enumerate(ranked[:20], 1):
        r = info["rets"]
        w_strs = [f"{v:>7.1f}%" for v in r]
        while len(w_strs) < 3:
            w_strs.append("     N/A")
        print(f"  {i:<5} {tag:<18} {info['avg_ret']:>6.1f}% {info['avg_pf']:>6.2f}  "
              f"{w_strs[0]} {w_strs[1]} {w_strs[2]}")

    # ── save ────────────────────────────────────────────────────────────
    out_file = OUT_DIR / "sweep_r3_results.json"
    save_data = {
        "all_results": all_results,
        "ranking": [{"tag": t, **info} for t, info in ranked],
        "total_time_s": round(total, 1),
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(save_data, f, indent=2, default=str)
    print(f"\n  Results → {out_file}")


if __name__ == "__main__":
    run()
