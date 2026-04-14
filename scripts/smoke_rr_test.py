#!/usr/bin/env python3
"""
Smoke test: compare rr_mode 'trailing' vs '1:2' on a single symbol (BTCUSDT, 15m)
Saves summaries/trades/equity under data/ with prefixes smoke_trailing / smoke_rr12
"""
import os
import shutil
import json
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.backtester import Backtester, BacktestConfig

TMP_DIR = os.path.join("data", "tmp_smoke_15m")
SRC = os.path.join("data", "history", "15m", "BTCUSDT.csv")

if not os.path.exists(SRC):
    print("ERROR: BTCUSDT.csv not found in data/history/15m")
    sys.exit(1)

os.makedirs(TMP_DIR, exist_ok=True)
DST = os.path.join(TMP_DIR, "BTCUSDT.csv")
shutil.copyfile(SRC, DST)


def run_one(cfg, prefix):
    cfg.verbose = False
    bt = Backtester(cfg)
    prepared = bt.prepare_data(TMP_DIR)
    if "error" in prepared:
        print("ERROR prepare:", prepared)
        return prepared
    report = bt.run_prepared(prepared)
    bt.save_results(out_dir="data", prefix=prefix, summary=report)
    with open(os.path.join("data", f"{prefix}_summary.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return report


# trailing run (baseline)
cfg = BacktestConfig()
cfg.bar_minutes = 15
cfg.rr_mode = "trailing"
res_trail = run_one(cfg, "smoke_trailing")

# rr 1:2 run
cfg2 = BacktestConfig()
cfg2.bar_minutes = 15
cfg2.rr_mode = "1:2"
res_rr12 = run_one(cfg2, "smoke_rr12")

print("--- RESULTS ---")
print("trailing exit_reasons:", res_trail.get("exit_reasons") if isinstance(res_trail, dict) else res_trail)
print("rr12 exit_reasons:", res_rr12.get("exit_reasons") if isinstance(res_rr12, dict) else res_rr12)
