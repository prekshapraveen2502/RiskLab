import pandas as pd
import pytest

from src.risk.historical import (
    calculate_expected_shortfall,
    calculate_historical_var,
)

RETURNS = [-0.04, -0.03, -0.02, -0.01, 0.00, 0.01, 0.02, 0.03, 0.04, 0.05]

LONG_RETURNS = [
    -0.10, -0.08, -0.06, -0.04, -0.03,
    -0.02, -0.01, 0.00, 0.01, 0.02,
    0.03, 0.04, 0.05, 0.06, 0.07,
    0.08, 0.09, 0.10, 0.11, 0.12,
]


def make_returns():
    return pd.Series(RETURNS, name="portfolio_return")


def make_long_returns():
    return pd.Series(LONG_RETURNS, name="portfolio_return")


def test_historical_var_at_90_percent():
    var = calculate_historical_var(make_returns(), confidence_level=0.90)

    assert var == pytest.approx(0.031)


def test_historical_var_uses_default_95_percent_confidence():
    var = calculate_historical_var(make_returns())

    assert var == pytest.approx(0.0355)


def test_higher_confidence_produces_higher_var():
    returns = make_returns()

    var_90 = calculate_historical_var(returns, confidence_level=0.90)
    var_95 = calculate_historical_var(returns, confidence_level=0.95)

    assert var_95 > var_90


def test_empty_returns_fail():
    with pytest.raises(ValueError, match="cannot be empty"):
        calculate_historical_var(pd.Series([], dtype=float))


def test_missing_returns_fail():
    returns = pd.Series([-0.04, None, 0.02, 0.03])

    with pytest.raises(ValueError, match="missing values"):
        calculate_historical_var(returns)


@pytest.mark.parametrize("confidence_level", [0, 1, -0.10, 1.10])
def test_invalid_confidence_levels_fail(confidence_level):
    with pytest.raises(ValueError, match="between 0 and 1"):
        calculate_historical_var(make_returns(), confidence_level=confidence_level)


def test_historical_var_returns_python_float():
    var = calculate_historical_var(make_returns())

    assert type(var) is float


def test_expected_shortfall_at_90_percent():
    expected_shortfall = calculate_expected_shortfall(
        make_long_returns(), confidence_level=0.90
    )

    assert expected_shortfall == pytest.approx(0.09)


def test_expected_shortfall_uses_default_95_percent_confidence():
    expected_shortfall = calculate_expected_shortfall(make_long_returns())

    assert expected_shortfall == pytest.approx(0.10)


def test_expected_shortfall_is_at_least_var():
    returns = make_long_returns()

    var = calculate_historical_var(returns, confidence_level=0.90)
    expected_shortfall = calculate_expected_shortfall(returns, confidence_level=0.90)

    assert expected_shortfall >= var


def test_expected_shortfall_includes_returns_beyond_var_threshold():
    returns = make_long_returns()
    tail = [-0.10, -0.08]

    expected_shortfall = calculate_expected_shortfall(returns, confidence_level=0.90)

    assert expected_shortfall == pytest.approx(-sum(tail) / len(tail))
    assert expected_shortfall == pytest.approx(0.09)


def test_expected_shortfall_empty_returns_fail():
    with pytest.raises(ValueError, match="cannot be empty"):
        calculate_expected_shortfall(pd.Series([], dtype=float))


def test_expected_shortfall_missing_returns_fail():
    returns = pd.Series([-0.10, None, 0.02, 0.03])

    with pytest.raises(ValueError, match="missing values"):
        calculate_expected_shortfall(returns)


@pytest.mark.parametrize("confidence_level", [0, 1, -0.10, 1.10])
def test_expected_shortfall_invalid_confidence_levels_fail(confidence_level):
    with pytest.raises(ValueError, match="between 0 and 1"):
        calculate_expected_shortfall(
            make_long_returns(), confidence_level=confidence_level
        )


def test_expected_shortfall_returns_python_float():
    expected_shortfall = calculate_expected_shortfall(make_long_returns())

    assert type(expected_shortfall) is float
