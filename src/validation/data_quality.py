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


def validate_market_data(
    prices: pd.DataFrame,
    expected_tickers: list[str],
    max_missing_pct: float = 0.01,
) -> None:
    if prices.empty:
        raise ValueError("Market data is empty")

    missing_tickers = [ticker for ticker in expected_tickers if ticker not in prices.columns]
    if missing_tickers:
        raise ValueError(f"Market data is missing tickers: {missing_tickers}")

    duplicate_dates = prices.index[prices.index.duplicated()].unique()
    if len(duplicate_dates) > 0:
        raise ValueError(f"Market data contains duplicate dates: {list(duplicate_dates)}")

    if not prices.index.is_monotonic_increasing:
        raise ValueError("Market data is not in chronological order")

    non_positive = prices.columns[(prices <= 0).any()]
    if len(non_positive) > 0:
        raise ValueError(
            f"Market data contains non-positive prices for tickers: {list(non_positive)}"
        )

    missing_pct = prices.isna().mean()
    excessive = missing_pct[missing_pct > max_missing_pct]
    if not excessive.empty:
        reported = ", ".join(f"{ticker} {pct:.2%}" for ticker, pct in excessive.items())
        raise ValueError(
            f"Market data exceeds {max_missing_pct:.2%} missing values for tickers: {reported}"
        )
