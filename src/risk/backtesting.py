import pandas as pd


def detect_var_breaches(
    portfolio_returns: pd.Series,
    var_forecasts: pd.Series,
) -> pd.Series:
    if not portfolio_returns.index.equals(var_forecasts.index):
        raise ValueError("Portfolio returns and VaR forecasts must have matching indexes")

    if portfolio_returns.isna().any():
        raise ValueError("Portfolio returns contain missing values")

    breaches = pd.Series(
        pd.NA,
        index=portfolio_returns.index,
        dtype="boolean",
        name="var_breach",
    )

    valid_forecasts = var_forecasts.notna()

    breaches.loc[valid_forecasts] = (
        portfolio_returns.loc[valid_forecasts]
        < -var_forecasts.loc[valid_forecasts]
    )

    return breaches


def summarize_var_backtest(
    breaches: pd.Series,
    confidence_level: float = 0.95,
) -> dict:
    if not 0 < confidence_level < 1:
        raise ValueError("Confidence level must be between 0 and 1")

    evaluated = breaches.dropna()

    if evaluated.empty:
        raise ValueError("No evaluated VaR forecasts available")

    observations = int(evaluated.size)
    breach_count = int(evaluated.sum())

    return {
        "observations": observations,
        "breaches": breach_count,
        "breach_rate": float(breach_count / observations),
        "expected_breach_rate": float(1 - confidence_level),
    }