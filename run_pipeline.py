from pathlib import Path

import pandas as pd

from src.ingestion.yfinance_provider import YFinanceProvider
from src.risk.backtesting import (
    detect_var_breaches,
    kupiec_unconditional_coverage_test,
    summarize_var_backtest,
)
from src.risk.historical import calculate_expected_shortfall, calculate_historical_var
from src.risk.rolling import calculate_rolling_historical_var
from src.transformation.returns import (
    calculate_asset_returns,
    calculate_portfolio_returns,
)
from src.validation.data_quality import validate_market_data, validate_portfolio

START_DATE = "2018-01-01"
END_DATE = "2026-09-01"
ROLLING_WINDOW = 250
CONFIDENCE_LEVEL = 0.95

PORTFOLIO_PATH = Path(__file__).parent / "config" / "portfolio.csv"


def load_portfolio(portfolio_path: Path = PORTFOLIO_PATH) -> pd.DataFrame:
    return pd.read_csv(portfolio_path)


def run_analysis(
    provider=None,
    portfolio_path: Path = PORTFOLIO_PATH,
) -> dict:
    provider = provider if provider is not None else YFinanceProvider()

    portfolio = load_portfolio(portfolio_path)
    validate_portfolio(portfolio)

    tickers = portfolio["ticker"].tolist()

    prices = provider.get_daily_prices(
        tickers=tickers,
        start_date=START_DATE,
        end_date=END_DATE,
    )
    validate_market_data(prices, expected_tickers=tickers)

    asset_returns = calculate_asset_returns(prices)
    portfolio_returns = calculate_portfolio_returns(asset_returns, portfolio)

    # Downstream risk models reject NaN, so surface the cause instead of their generic error.
    if portfolio_returns.isna().any():
        missing_dates = portfolio_returns.index[portfolio_returns.isna()]
        raise ValueError(
            "Portfolio returns contain missing values on "
            f"{len(missing_dates)} dates (first: {missing_dates[0].date()}). "
            "Resolve the underlying price gaps before risk modeling; "
            "this pipeline will not fill or drop them silently."
        )

    historical_var = calculate_historical_var(
        portfolio_returns, confidence_level=CONFIDENCE_LEVEL
    )
    expected_shortfall = calculate_expected_shortfall(
        portfolio_returns, confidence_level=CONFIDENCE_LEVEL
    )

    rolling_var = calculate_rolling_historical_var(
        portfolio_returns,
        window=ROLLING_WINDOW,
        confidence_level=CONFIDENCE_LEVEL,
    )
    breaches = detect_var_breaches(portfolio_returns, rolling_var)

    backtest = summarize_var_backtest(breaches, confidence_level=CONFIDENCE_LEVEL)
    kupiec_test = kupiec_unconditional_coverage_test(
        breaches, confidence_level=CONFIDENCE_LEVEL
    )

    return {
        "portfolio": {
            "tickers": tickers,
            "weights": {
                ticker: float(weight)
                for ticker, weight in zip(portfolio["ticker"], portfolio["weight"])
            },
        },
        "analysis_period": {
            "start_date": prices.index[0].strftime("%Y-%m-%d"),
            "end_date": prices.index[-1].strftime("%Y-%m-%d"),
            "price_observations": int(len(prices)),
            "return_observations": int(len(portfolio_returns)),
        },
        "risk_metrics": {
            "historical_var_95": historical_var,
            "expected_shortfall_95": expected_shortfall,
        },
        "backtest": backtest,
        "kupiec_test": kupiec_test,
        # Retained for the persistence milestone; not part of the serializable report.
        "data": {
            "prices": prices,
            "asset_returns": asset_returns,
            "portfolio_returns": portfolio_returns,
            "rolling_var": rolling_var,
            "breaches": breaches,
        },
    }


def format_summary(results: dict) -> str:
    portfolio = results["portfolio"]
    period = results["analysis_period"]
    metrics = results["risk_metrics"]
    backtest = results["backtest"]
    kupiec = results["kupiec_test"]

    weights = ", ".join(
        f"{ticker} {weight:.0%}" for ticker, weight in portfolio["weights"].items()
    )

    return "\n".join(
        [
            "=== RiskLab Risk Analysis ===",
            "",
            f"Portfolio:            {', '.join(portfolio['tickers'])}",
            f"Weights:              {weights}",
            f"Analysis Period:      {period['start_date']} to {period['end_date']}",
            f"Price Observations:   {period['price_observations']}",
            f"Return Observations:  {period['return_observations']}",
            "",
            f"Historical VaR (95%): {metrics['historical_var_95']:.4%}",
            f"Expected Shortfall:   {metrics['expected_shortfall_95']:.4%}",
            "",
            f"Rolling Window:       {ROLLING_WINDOW} days",
            f"Evaluated Forecasts:  {backtest['observations']}",
            f"Breaches:             {backtest['breaches']}",
            f"Observed Breach Rate: {backtest['breach_rate']:.4%}",
            f"Expected Breach Rate: {backtest['expected_breach_rate']:.4%}",
            "",
            f"Kupiec LR Statistic:  {kupiec['lr_statistic']:.6f}",
            f"Kupiec p-value:       {kupiec['p_value']:.6f}",
            f"Significance Level:   {kupiec['significance_level']:.2%}",
            f"Reject Null:          {kupiec['reject_null']}",
            "",
            (
                "Unconditional coverage rejected."
                if kupiec["reject_null"]
                else "Breach frequency is consistent with the VaR model."
            ),
        ]
    )


if __name__ == "__main__":
    results = run_analysis()
    print(format_summary(results))
