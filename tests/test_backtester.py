import numpy as np

from core.backtester import Backtester, BacktestConfig


def test_fixed_leverage_and_symbol_filters():
    cfg = BacktestConfig(
        fixed_leverage=3,
        require_standard_symbols=True,
        exclude_symbols=["BTCDOMUSDT"],
    )
    backtester = Backtester(cfg)

    assert backtester._lev(0.95) == 3
    assert backtester._is_symbol_enabled("DOGEUSDT") is True
    assert backtester._is_symbol_enabled("BTCDOMUSDT") is False
    assert backtester._is_symbol_enabled("币安人生USDT") is False


def test_entry_signal_uses_runtime_thresholds():
    cfg = BacktestConfig(
        rsi_entry_min=56.0,
        rsi_entry_max=74.0,
        volume_mult=2.0,
        min_close_ratio=0.65,
    )
    backtester = Backtester(cfg)
    symbol_data = {
        "trend_up": [True, True],
        "rsi": [55.9, 60.0],
        "vol_r": [2.5, 1.9],
        "prev_hi": [10.0, 10.0],
        "cr": [0.80, 0.80],
        "cl": [10.5, 10.5],
    }

    assert backtester._entry_signal(symbol_data, 0) is False
    assert backtester._entry_signal(symbol_data, 1) is False

    symbol_data["vol_r"][1] = 2.1
    assert backtester._entry_signal(symbol_data, 1) is True


def test_period_stats_include_annualized_sharpe_and_calmar():
    backtester = Backtester(BacktestConfig(verbose=False))
    backtester._timeline_start = __import__("pandas").Timestamp("2024-01-01 00:00:00")
    backtester._timeline_end = __import__("pandas").Timestamp("2025-01-01 00:00:00")
    backtester._bar_seconds = 24 * 3600
    backtester._equity_points = [100.0, 101.0, 103.0, 102.0, 105.0, 110.0]
    backtester.max_dd = 0.10

    stats = backtester._compute_period_stats(100.0, 110.0)

    assert stats["annualized_return_pct"] is not None
    assert stats["annualized_return_pct"] > 9.0
    assert stats["sharpe_ratio"] is not None
    assert isinstance(stats["sharpe_ratio"], float)
    assert stats["calmar_ratio"] is not None
    assert isinstance(stats["calmar_ratio"], float)
    assert stats["calmar_ratio"] > 0


def test_slice_prepared_filters_dates_and_keeps_date_only_end_inclusive():
    prepared = {
        "symbols": {
            "AAAUSDT": {
                "da": np.array([
                    "2024-01-01 00:00:00",
                    "2024-01-01 12:00:00",
                    "2024-01-02 00:00:00",
                ], dtype=object),
                "cl": np.array([1.0, 2.0, 3.0]),
                "n": 3,
            }
        },
        "btc_regime": {
            "2024-01-01 00:00:00": True,
            "2024-01-01 12:00:00": False,
            "2024-01-02 00:00:00": True,
        },
        "timeline": [
            "2024-01-01 00:00:00",
            "2024-01-01 12:00:00",
            "2024-01-02 00:00:00",
        ],
    }

    sliced = Backtester.slice_prepared(
        prepared,
        start_date="2024-01-01",
        end_date="2024-01-01",
    )

    assert sliced["timeline"] == [
        "2024-01-01 00:00:00",
        "2024-01-01 12:00:00",
    ]
    assert sliced["symbols"]["AAAUSDT"]["n"] == 2
    assert sliced["symbols"]["AAAUSDT"]["cl"].tolist() == [1.0, 2.0]
    assert list(sliced["btc_regime"]) == [
        "2024-01-01 00:00:00",
        "2024-01-01 12:00:00",
    ]


def test_slice_prepared_rejects_inverted_range():
    prepared = {
        "symbols": {"AAAUSDT": {"da": np.array(["2024-01-01 00:00:00"], dtype=object), "n": 1}},
        "btc_regime": {},
        "timeline": ["2024-01-01 00:00:00"],
    }

    sliced = Backtester.slice_prepared(
        prepared,
        start_date="2024-01-02",
        end_date="2024-01-01",
    )

    assert sliced == {"error": "start_date after end_date"}
