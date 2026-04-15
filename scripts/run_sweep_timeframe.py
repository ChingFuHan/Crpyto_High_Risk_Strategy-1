import argparse
import json
from pathlib import Path

import scripts.comprehensive_sweep as sweep


def main():
    ap = argparse.ArgumentParser(description="Run a single comprehensive sweep timeframe")
    ap.add_argument("timeframe", choices=["1h", "15m", "5m"])
    args = ap.parse_args()

    summary = sweep.run_timeframe(args.timeframe)
    out = Path("logs/comprehensive_sweep") / f"sweep_{args.timeframe}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"SAVED {out}")


if __name__ == "__main__":
    main()
