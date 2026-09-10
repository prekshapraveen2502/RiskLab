import pandas as pd
import pytest

from src.risk.backtesting import detect_var_breaches

DATES = pd.to_datetime(
    ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]
)


def make_returns():
    return pd.Series([-0.01, -0.02, -0.04, 0.01], index=DATES, name="portfolio_return")


def make_forecasts():
    return pd.Series([None, 0.025, 0.025, 0.025], index=DATES, name="historical_var")


def test_detect_var_breaches_returns_expected_states():
    expected = pd.Series(
        [pd.NA, False, True, False],
        index=DATES,
        dtype="boolean",
        name="var_breach",
    )

    breaches = detect_var_breaches(make_returns(), make_forecasts())

    pd.testing.assert_series_equal(breaches, expected)


def test_missing_var_forecast_is_not_evaluated():
    breaches = detect_var_breaches(make_returns(), make_forecasts())

    assert pd.isna(breaches.iloc[0])
    assert breaches.iloc[0] is not False
    assert breaches.isna().sum() == 1


def test_loss_equal_to_var_is_not_a_breach():
    dates = DATES[:1]
    returns = pd.Series([-0.025], index=dates, name="portfolio_return")
    forecasts = pd.Series([0.025], index=dates, name="historical_var")

    breaches = detect_var_breaches(returns, forecasts)

    assert breaches.iloc[0] == False


def test_loss_worse_than_var_is_a_breach():
    dates = DATES[:1]
    returns = pd.Series([-0.026], index=dates, name="portfolio_return")
    forecasts = pd.Series([0.025], index=dates, name="historical_var")

    breaches = detect_var_breaches(returns, forecasts)

    assert breaches.iloc[0] == True


def test_matching_indexes_are_required():
    forecasts = make_forecasts()
    forecasts.index = pd.to_datetime(
        ["2025-02-03", "2025-02-04", "2025-02-05", "2025-02-06"]
    )

    with pytest.raises(ValueError, match="matching indexes"):
        detect_var_breaches(make_returns(), forecasts)


def test_missing_portfolio_return_fails():
    returns = pd.Series([-0.01, None, -0.04, 0.01], index=DATES)

    with pytest.raises(ValueError, match="missing values"):
        detect_var_breaches(returns, make_forecasts())


def test_breach_output_metadata():
    returns = make_returns()

    breaches = detect_var_breaches(returns, make_forecasts())

    assert isinstance(breaches.dtype, pd.BooleanDtype)
    assert breaches.name == "var_breach"
    pd.testing.assert_index_equal(breaches.index, returns.index)


def test_detect_var_breaches_does_not_modify_inputs():
    returns = make_returns()
    forecasts = make_forecasts()
    original_returns = returns.copy()
    original_forecasts = forecasts.copy()

    detect_var_breaches(returns, forecasts)

    pd.testing.assert_series_equal(returns, original_returns)
    pd.testing.assert_series_equal(forecasts, original_forecasts)
