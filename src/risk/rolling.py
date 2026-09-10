import pandas as pd


def calculate_rolling_historical_var(
    portfolio_returns: pd.Series,
    window: int = 250,
    confidence_level: float = 0.95,
) -> pd.Series:
    if portfolio_returns.empty:
        raise ValueError("Portfolio returns cannot be empty")

    if portfolio_returns.isna().any():
        raise ValueError("Portfolio returns contain missing values")

    if window <= 0:
        raise ValueError("Window must be greater than 0")

    if not 0 < confidence_level < 1:
        raise ValueError("Confidence level must be between 0 and 1")

    tail_probability = 1 - confidence_level

    lagged_returns = portfolio_returns.shift(1)

    rolling_threshold = lagged_returns.rolling(
        window=window,
        min_periods=window,
    ).quantile(
        tail_probability,
        interpolation="linear",
    )

    rolling_var = -rolling_threshold
    rolling_var.name = "historical_var"

    return rolling_var