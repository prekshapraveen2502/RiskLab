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