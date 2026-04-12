"""
Download ALL Binance USDⓈ-M futures historical OHLCV data.

Output : data/history/{interval}/{SYMBOL}.csv
Columns: da,op,hi,lo,cl,vol   (da = YYYY-MM-DD HH:MM:SS  UTC)

Usage:
    python -m scripts.download_history                        # all pairs, 1h
    python -m scripts.download_history --interval 15m
    python -m scripts.download_history --interval 5m --delay 0.05
    python -m scripts.download_history --symbols BTCUSDT ETHUSDT
    python -m scripts.download_history --resume               # skip existing
"""
import argparse
import os
import sys
import time
import requests
import pandas as pd
from datetime import datetime, timezone

BASE_URL = "https://fapi.binance.com"
KLINE_LIMIT = 1000          # per-request candle count (weight ≈ 5)
DEFAULT_REQUEST_DELAY = 0.05
MAX_RETRIES = 4


def safe_display(text: str) -> str:
    """Return an ASCII-safe representation for console output."""
    return text.encode("ascii", errors="backslashreplace").decode("ascii")


def get_all_usdt_perpetuals() -> list:
    """Return sorted list of all active USDT-M perpetual symbols."""
    resp = requests.get(f"{BASE_URL}/fapi/v1/exchangeInfo", timeout=30)
    resp.raise_for_status()
    info = resp.json()
    symbols = []
    for s in info["symbols"]:
        if (
            s.get("contractType") == "PERPETUAL"
            and s.get("quoteAsset") == "USDT"
            and s.get("status") == "TRADING"
        ):
            symbols.append(s["symbol"])
    return sorted(symbols)


def download_klines(symbol: str, interval: str = "1h", request_delay: float = DEFAULT_REQUEST_DELAY) -> list:
    """Download full history of klines for *symbol* with auto-pagination."""
    rows = []
    # Binance Futures launched 2019-09-08; start from 2019-09-01 UTC
    start_ms = int(datetime(2019, 9, 1, tzinfo=timezone.utc).timestamp() * 1000)

    while True:
        params = {"symbol": symbol, "interval": interval, "limit": KLINE_LIMIT,
                  "startTime": start_ms}

        data = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.get(
                    f"{BASE_URL}/fapi/v1/klines", params=params, timeout=30
                )
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 30))
                    print(f"  rate-limited, waiting {wait}s ...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as exc:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                else:
                    print(f"  failed after {MAX_RETRIES} retries: {exc}")
                    return rows

        if not data:
            break

        for k in data:
            dt = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
            rows.append({
                "da": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "op": k[1],
                "hi": k[2],
                "lo": k[3],
                "cl": k[4],
                "vol": k[5],
            })

        start_ms = data[-1][0] + 1          # next page starts 1 ms after last
        if len(data) < KLINE_LIMIT:
            break
        if request_delay > 0:
            time.sleep(request_delay)

    return rows


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Download Binance futures OHLCV")
    ap.add_argument("--interval", default="1h", help="Kline interval (default 1h)")
    ap.add_argument("--symbols", nargs="*", help="Specific symbols (default: all)")
    ap.add_argument("--delay", type=float, default=DEFAULT_REQUEST_DELAY,
                    help=f"Delay in seconds between paginated API calls (default {DEFAULT_REQUEST_DELAY})")
    ap.add_argument("--resume", action="store_true", default=True,
                    help="Skip files that already exist (default True)")
    args = ap.parse_args()

    out_dir = os.path.join("data", "history", args.interval)
    os.makedirs(out_dir, exist_ok=True)

    if args.symbols:
        symbols = [s.upper() for s in args.symbols]
    else:
        print("Fetching exchange info ...")
        symbols = get_all_usdt_perpetuals()

    total = len(symbols)
    print(f"Symbols : {total}")
    print(f"Interval: {args.interval}")
    print(f"Output  : {out_dir}")
    print(f"Delay   : {args.delay}s")
    print("-" * 60)

    downloaded, skipped = 0, 0
    t0 = time.time()

    for i, sym in enumerate(symbols, 1):
        path = os.path.join(out_dir, f"{sym}.csv")

        if args.resume and os.path.exists(path):
            skipped += 1
            continue

        display_sym = safe_display(sym)
        print(f"[{i:>3}/{total}] {display_sym:<16}", end="", flush=True)
        rows = download_klines(sym, args.interval, request_delay=args.delay)

        if rows:
            pd.DataFrame(rows).to_csv(path, index=False)
            print(f" -> {len(rows):>7,} candles")
            downloaded += 1
        else:
            print(" -> (no data)")

        if args.delay > 0:
            time.sleep(args.delay)

    elapsed = time.time() - t0
    print("-" * 60)
    print(f"Done  downloaded={downloaded}  skipped={skipped}  "
          f"total={total}  elapsed={elapsed/60:.1f} min")


if __name__ == "__main__":
    main()
