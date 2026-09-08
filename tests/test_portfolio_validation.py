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
