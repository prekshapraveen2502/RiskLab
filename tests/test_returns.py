import pandas as pd
import pytest

from src.transformation.returns import (
    calculate_asset_returns,
    calculate_portfolio_returns,
)

DATES = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
RETURN_DATES = DATES[1:]


def make_prices():
    return pd.DataFrame(
        {
            "SPY": [100.0, 105.0, 102.0],
            "QQQ": [200.0, 190.0, 209.0],
        },
        index=DATES,
    )


def make_asset_returns():
    return pd.DataFrame(
        {
            "GLD": [0.01, 0.00],
            "QQQ": [-0.01, 0.03],
            "SPY": [0.02, -0.01],
        },
        index=RETURN_DATES,
    )


def make_portfolio():
    return pd.DataFrame(
        {
            "ticker": ["SPY", "QQQ", "GLD"],
            "weight": [0.50, 0.30, 0.20],
        }
    )


def test_asset_returns_are_calculated_correctly():
    expected = pd.DataFrame(
        {
            "SPY": [0.05, -0.0285714286],
            "QQQ": [-0.05, 0.10],
        },
        index=DATES[1:],
    )

    returns = calculate_asset_returns(make_prices())

    pd.testing.assert_frame_equal(returns, expected)


def test_first_row_is_removed():
    prices = make_prices()

    returns = calculate_asset_returns(prices)

    assert len(prices) == 3
    assert len(returns) == 2
    assert returns.index[0] == prices.index[1]


def test_columns_are_preserved():
    returns = calculate_asset_returns(make_prices())

    pd.testing.assert_index_equal(returns.columns, pd.Index(["SPY", "QQQ"]))


def test_missing_price_is_not_filled():
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"])
    prices = pd.DataFrame({"SPY": [100.0, None, 102.0, 103.0]}, index=dates)

    returns = calculate_asset_returns(prices)

    assert pd.isna(returns.loc[dates[1], "SPY"])
    assert pd.isna(returns.loc[dates[2], "SPY"])
    assert returns.loc[dates[3], "SPY"] == pytest.approx(103.0 / 102.0 - 1.0)


def test_portfolio_returns_are_calculated_correctly():
    expected = pd.Series([0.009, 0.004], index=RETURN_DATES, name="portfolio_return")

    portfolio_returns = calculate_portfolio_returns(make_asset_returns(), make_portfolio())

    pd.testing.assert_series_equal(portfolio_returns, expected)


def test_portfolio_returns_align_by_ticker():
    asset_returns = make_asset_returns()
    shuffled = asset_returns[["SPY", "GLD", "QQQ"]]

    expected = calculate_portfolio_returns(asset_returns, make_portfolio())
    actual = calculate_portfolio_returns(shuffled, make_portfolio())

    assert list(asset_returns.columns) != list(shuffled.columns)
    pd.testing.assert_series_equal(actual, expected)


def test_missing_portfolio_ticker_fails():
    asset_returns = make_asset_returns()[["SPY", "QQQ"]]

    with pytest.raises(ValueError, match="missing portfolio tickers"):
        calculate_portfolio_returns(asset_returns, make_portfolio())


def test_missing_asset_return_produces_missing_portfolio_return():
    asset_returns = make_asset_returns()
    asset_returns.loc[RETURN_DATES[1], "GLD"] = None

    portfolio_returns = calculate_portfolio_returns(asset_returns, make_portfolio())

    assert portfolio_returns.loc[RETURN_DATES[0]] == pytest.approx(0.009)
    assert pd.isna(portfolio_returns.loc[RETURN_DATES[1]])


def test_portfolio_return_metadata():
    asset_returns = make_asset_returns()

    portfolio_returns = calculate_portfolio_returns(asset_returns, make_portfolio())

    assert portfolio_returns.name == "portfolio_return"
    pd.testing.assert_index_equal(portfolio_returns.index, asset_returns.index)
