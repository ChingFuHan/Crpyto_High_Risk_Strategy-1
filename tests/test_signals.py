import pandas as pd

from core.signals import compute_indicators


def test_compute_indicators_uses_prior_breakout_levels():
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=30, freq="5min"),
            "open": [float(i) for i in range(1, 31)],
            "high": [float(i) for i in range(2, 32)],
            "low": [float(i) for i in range(0, 30)],
            "close": [float(i) for i in range(1, 31)],
            "volume": [1000.0 + i * 10 for i in range(30)],
        }
    )

    enriched = compute_indicators(df)

    assert "ema_9" in enriched.columns
    assert "rsi_14" in enriched.columns
    assert "prior_high_20" in enriched.columns
    assert "prior_low_20" in enriched.columns
    assert pd.notna(enriched.iloc[-1]["ema_9"])
    assert enriched.iloc[20]["prior_high_20"] == 21.0
    assert enriched.iloc[20]["prior_low_20"] == 0.0
