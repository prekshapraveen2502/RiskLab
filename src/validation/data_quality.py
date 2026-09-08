import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ("ticker", "weight")


def validate_portfolio(portfolio: pd.DataFrame) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in portfolio.columns]
    if missing:
        raise ValueError(f"Portfolio is missing required columns: {missing}")

    missing_tickers = portfolio.index[portfolio["ticker"].isna()]
    if not missing_tickers.empty:
        raise ValueError(f"Portfolio has missing tickers in rows: {list(missing_tickers)}")

    missing_weights = portfolio.loc[portfolio["weight"].isna(), "ticker"]
    if not missing_weights.empty:
        raise ValueError(f"Portfolio has missing weights for tickers: {list(missing_weights)}")

    duplicates = portfolio["ticker"][portfolio["ticker"].duplicated()].unique()
    if len(duplicates) > 0:
        raise ValueError(f"Portfolio contains duplicate tickers: {list(duplicates)}")

    negative = portfolio.loc[portfolio["weight"] < 0, "ticker"]
    if not negative.empty:
        raise ValueError(f"Portfolio contains negative weights: {list(negative)}")

    total = portfolio["weight"].sum()
    if not np.isclose(total, 1.0):
        raise ValueError(f"Portfolio weights must sum to 1.0, got {total}")
