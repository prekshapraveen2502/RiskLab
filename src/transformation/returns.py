import pandas as pd


def calculate_asset_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change(fill_method=None).iloc[1:]

def calculate_portfolio_returns(
    asset_returns: pd.DataFrame,
    portfolio: pd.DataFrame,
) -> pd.Series:
    weights = portfolio.set_index("ticker")["weight"]

    missing_tickers = [
        ticker
        for ticker in weights.index
        if ticker not in asset_returns.columns
    ]

    if missing_tickers:
        raise ValueError(
            f"Asset returns are missing portfolio tickers: {missing_tickers}"
        )

    aligned_returns = asset_returns.loc[:, weights.index]

    weighted_returns = aligned_returns.mul(
        weights,
        axis="columns",
    )

    portfolio_returns = weighted_returns.sum(
        axis=1,
        min_count=len(weights),
    )

    portfolio_returns.name = "portfolio_return"

    return portfolio_returns