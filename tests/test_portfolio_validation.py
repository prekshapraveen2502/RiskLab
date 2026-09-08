import pandas as pd
import pytest

from src.validation.data_quality import validate_portfolio


def test_valid_portfolio_passes():
    portfolio = pd.DataFrame(
        {
            "ticker": ["SPY", "QQQ", "TLT"],
            "weight": [0.5, 0.3, 0.2],
        }
    )

    validate_portfolio(portfolio)


def test_negative_weight_fails():
    portfolio = pd.DataFrame(
        {
            "ticker": ["SPY", "QQQ", "TLT"],
            "weight": [0.6, -0.1, 0.5],
        }
    )

    with pytest.raises(ValueError):
        validate_portfolio(portfolio)


def test_missing_ticker_column_fails():
    portfolio = pd.DataFrame({"weight": [0.5, 0.3, 0.2]})

    with pytest.raises(ValueError, match="missing required columns"):
        validate_portfolio(portfolio)


def test_missing_weight_column_fails():
    portfolio = pd.DataFrame({"ticker": ["SPY", "QQQ", "TLT"]})

    with pytest.raises(ValueError, match="missing required columns"):
        validate_portfolio(portfolio)


def test_missing_ticker_value_fails():
    portfolio = pd.DataFrame(
        {
            "ticker": ["SPY", None, "TLT"],
            "weight": [0.5, 0.3, 0.2],
        }
    )

    with pytest.raises(ValueError, match="missing tickers"):
        validate_portfolio(portfolio)


def test_missing_weight_value_fails():
    portfolio = pd.DataFrame(
        {
            "ticker": ["SPY", "QQQ", "TLT"],
            "weight": [0.5, None, 0.5],
        }
    )

    with pytest.raises(ValueError, match="missing weights"):
        validate_portfolio(portfolio)


def test_duplicate_ticker_fails():
    portfolio = pd.DataFrame(
        {
            "ticker": ["SPY", "SPY", "TLT"],
            "weight": [0.5, 0.3, 0.2],
        }
    )

    with pytest.raises(ValueError, match="duplicate tickers"):
        validate_portfolio(portfolio)


def test_weights_not_summing_to_one_fails():
    portfolio = pd.DataFrame(
        {
            "ticker": ["SPY", "QQQ", "TLT"],
            "weight": [0.5, 0.3, 0.1],
        }
    )

    with pytest.raises(ValueError, match="must sum to 1.0"):
        validate_portfolio(portfolio)
