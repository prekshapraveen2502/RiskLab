import pandas as pd


def calculate_historical_var(
    portfolio_returns: pd.Series,
    confidence_level: float = 0.95,
) -> float:

    if portfolio_returns.empty:
        raise ValueError("Portfolio returns cannot be empty")

    if portfolio_returns.isna().any():
        raise ValueError("Portfolio returns contain missing values")

    if not 0 < confidence_level < 1:
        raise ValueError("Confidence level must be between 0 and 1")

    tail_probability = 1 - confidence_level

    return_threshold = portfolio_returns.quantile(
        tail_probability,
        interpolation="linear",
    )

    historical_var = -return_threshold

    return float(historical_var)

def calculate_expected_shortfall(
    portfolio_returns: pd.Series,
    confidence_level: float = 0.95,
) -> float:
    if portfolio_returns.empty:
        raise ValueError("Portfolio returns cannot be empty")

    if portfolio_returns.isna().any():
        raise ValueError("Portfolio returns contain missing values")

    if not 0 < confidence_level < 1:
        raise ValueError("Confidence level must be between 0 and 1")

    tail_probability = 1 - confidence_level

    return_threshold = portfolio_returns.quantile(
        tail_probability,
        interpolation="linear",
    )

    tail_returns = portfolio_returns[
        portfolio_returns <= return_threshold
    ]

    expected_shortfall = -tail_returns.mean()

    return float(expected_shortfall)