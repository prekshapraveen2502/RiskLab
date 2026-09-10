import pandas as pd
import pytest

from src.risk.rolling import calculate_rolling_historical_var

DATES = pd.to_datetime(
    ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08"]
)
RETURNS = [-0.02, 0.01, -0.03, 0.02, -0.01]


def make_returns():
    return pd.Series(RETURNS, index=DATES, name="portfolio_return")


def make_long_returns(periods=260):
    values = [((index * 7) % 41 - 20) / 1000 for index in range(periods)]
    dates = pd.bdate_range("2024-01-01", periods=periods)
    return pd.Series(values, index=dates, name="portfolio_return")


def test_rolling_var_calculates_expected_values():
    rolling_var = calculate_rolling_historical_var(
        make_returns(), window=3, confidence_level=0.90
    )

    assert rolling_var.iloc[:3].isna().all()
    assert rolling_var.iloc[3] == pytest.approx(0.028)
    assert rolling_var.iloc[4] == pytest.approx(0.022)


def test_rolling_var_has_no_lookahead_bias():
    returns = make_returns()
    trailing_window = returns.iloc[:3]
    expected = -trailing_window.quantile(0.10, interpolation="linear")

    rolling_var = calculate_rolling_historical_var(
        returns, window=3, confidence_level=0.90
    )

    assert rolling_var.iloc[3] == pytest.approx(expected)

    perturbed = returns.copy()
    perturbed.iloc[3] = -0.99
    perturbed_var = calculate_rolling_historical_var(
        perturbed, window=3, confidence_level=0.90
    )

    assert perturbed_var.iloc[3] == pytest.approx(rolling_var.iloc[3])
    assert perturbed_var.iloc[4] != pytest.approx(rolling_var.iloc[4])


def test_first_valid_forecast_occurs_after_full_window():
    rolling_var = calculate_rolling_historical_var(
        make_returns(), window=3, confidence_level=0.90
    )

    assert rolling_var.iloc[:3].isna().all()
    assert rolling_var.first_valid_index() == DATES[3]


def test_rolling_var_preserves_index():
    returns = make_returns()

    rolling_var = calculate_rolling_historical_var(
        returns, window=3, confidence_level=0.90
    )

    pd.testing.assert_index_equal(rolling_var.index, returns.index)


def test_rolling_var_output_name():
    rolling_var = calculate_rolling_historical_var(
        make_returns(), window=3, confidence_level=0.90
    )

    assert rolling_var.name == "historical_var"


def test_rolling_var_does_not_modify_input():
    returns = make_returns()
    original = returns.copy()

    calculate_rolling_historical_var(returns, window=3, confidence_level=0.90)

    pd.testing.assert_series_equal(returns, original)


def test_empty_returns_fail():
    with pytest.raises(ValueError, match="cannot be empty"):
        calculate_rolling_historical_var(pd.Series([], dtype=float), window=3)


def test_missing_returns_fail():
    returns = pd.Series([-0.02, None, -0.03, 0.02, -0.01], index=DATES)

    with pytest.raises(ValueError, match="missing values"):
        calculate_rolling_historical_var(returns, window=3)


@pytest.mark.parametrize("window", [0, -1])
def test_invalid_window_fails(window):
    with pytest.raises(ValueError, match="greater than 0"):
        calculate_rolling_historical_var(make_returns(), window=window)


@pytest.mark.parametrize("confidence_level", [0, 1, -0.10, 1.10])
def test_invalid_confidence_levels_fail(confidence_level):
    with pytest.raises(ValueError, match="between 0 and 1"):
        calculate_rolling_historical_var(
            make_returns(), window=3, confidence_level=confidence_level
        )


def test_default_parameters():
    returns = make_long_returns()
    expected = -returns.iloc[:250].quantile(0.05, interpolation="linear")

    rolling_var = calculate_rolling_historical_var(returns)

    assert len(returns) > 250
    assert rolling_var.iloc[:250].isna().all()
    assert rolling_var.iloc[250] == pytest.approx(expected)
