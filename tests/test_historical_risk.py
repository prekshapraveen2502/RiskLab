import pandas as pd
import pytest

from src.risk.historical import calculate_historical_var

RETURNS = [-0.04, -0.03, -0.02, -0.01, 0.00, 0.01, 0.02, 0.03, 0.04, 0.05]


def make_returns():
    return pd.Series(RETURNS, name="portfolio_return")


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
