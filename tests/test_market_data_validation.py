import pandas as pd
import pytest

from src.validation.data_quality import validate_market_data

DATES = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"])
TICKERS = ["SPY", "QQQ"]


def make_prices(spy=None, qqq=None, index=DATES):
    return pd.DataFrame(
        {
            "SPY": spy if spy is not None else [100.0, 101.0, 102.0, 103.0],
            "QQQ": qqq if qqq is not None else [200.0, 201.0, 202.0, 203.0],
        },
        index=index,
    )


def test_valid_market_data_passes():
    validate_market_data(make_prices(), TICKERS)


def test_empty_dataframe_fails():
    with pytest.raises(ValueError, match="empty"):
        validate_market_data(pd.DataFrame(), TICKERS)


def test_missing_expected_ticker_fails():
    with pytest.raises(ValueError, match="missing tickers"):
        validate_market_data(make_prices(), ["SPY", "QQQ", "GLD"])


def test_duplicate_date_fails():
    duplicated = pd.to_datetime(["2025-01-02", "2025-01-02", "2025-01-06", "2025-01-07"])

    with pytest.raises(ValueError, match="duplicate dates"):
        validate_market_data(make_prices(index=duplicated), TICKERS)


def test_non_chronological_index_fails():
    with pytest.raises(ValueError, match="chronological"):
        validate_market_data(make_prices().iloc[::-1], TICKERS)


def test_zero_price_fails():
    with pytest.raises(ValueError, match="non-positive"):
        validate_market_data(make_prices(qqq=[200.0, 0.0, 202.0, 203.0]), TICKERS)


def test_negative_price_fails():
    with pytest.raises(ValueError, match="non-positive"):
        validate_market_data(make_prices(qqq=[200.0, -1.0, 202.0, 203.0]), TICKERS)


def test_missing_data_below_threshold_passes():
    prices = make_prices(qqq=[200.0, None, 202.0, 203.0])

    validate_market_data(prices, TICKERS, max_missing_pct=0.5)


def test_missing_data_above_threshold_fails():
    prices = make_prices(qqq=[200.0, None, 202.0, 203.0])

    with pytest.raises(ValueError, match="missing values"):
        validate_market_data(prices, TICKERS, max_missing_pct=0.1)
