import numpy as np
import pandas as pd
import pytest

from run_pipeline import (
    CONFIDENCE_LEVEL,
    END_DATE,
    ROLLING_WINDOW,
    START_DATE,
    load_portfolio,
    run_analysis,
)
from src.risk.rolling import calculate_rolling_historical_var

OBSERVATIONS = 700


class FakeProvider:
    def __init__(self, prices=None, error=None):
        self.prices = prices
        self.error = error
        self.calls = []

    def get_daily_prices(self, tickers, start_date, end_date):
        self.calls.append(
            {
                "tickers": list(tickers),
                "start_date": start_date,
                "end_date": end_date,
            }
        )

        if self.error is not None:
            raise self.error

        return self.prices.copy()


def configured_tickers():
    return load_portfolio()["ticker"].tolist()


def make_prices(tickers=None, observations=OBSERVATIONS, seed=7):
    tickers = tickers if tickers is not None else configured_tickers()
    dates = pd.bdate_range("2018-01-02", periods=observations)
    rng = np.random.default_rng(seed)

    return pd.DataFrame(
        {
            ticker: 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, observations)))
            for ticker in tickers
        },
        index=dates,
    )


def run_with_fake(prices=None, **kwargs):
    provider = FakeProvider(prices if prices is not None else make_prices())
    return run_analysis(provider=provider, **kwargs)


def test_pipeline_requests_configured_portfolio_tickers():
    provider = FakeProvider(make_prices())

    run_analysis(provider=provider)

    assert len(provider.calls) == 1
    assert provider.calls[0]["tickers"] == configured_tickers()
    assert provider.calls[0]["start_date"] == START_DATE
    assert provider.calls[0]["end_date"] == END_DATE


def test_pipeline_reports_configured_weights():
    results = run_with_fake()

    portfolio = load_portfolio()
    expected_weights = {
        ticker: float(weight)
        for ticker, weight in zip(portfolio["ticker"], portfolio["weight"])
    }

    assert results["portfolio"]["tickers"] == configured_tickers()
    assert results["portfolio"]["weights"] == expected_weights


def test_pipeline_enforces_real_portfolio_validation(tmp_path):
    portfolio_path = tmp_path / "portfolio.csv"
    portfolio_path.write_text("ticker,weight\nSPY,0.30\nQQQ,0.20\n")
    provider = FakeProvider(make_prices())

    with pytest.raises(ValueError, match="weights must sum to 1.0"):
        run_analysis(provider=provider, portfolio_path=portfolio_path)

    assert provider.calls == []


def test_pipeline_rejects_duplicate_portfolio_tickers(tmp_path):
    portfolio_path = tmp_path / "portfolio.csv"
    portfolio_path.write_text("ticker,weight\nSPY,0.50\nSPY,0.50\n")

    with pytest.raises(ValueError, match="duplicate tickers"):
        run_analysis(provider=FakeProvider(make_prices()), portfolio_path=portfolio_path)


def test_pipeline_output_structure():
    results = run_with_fake()

    assert set(results) == {
        "portfolio",
        "analysis_period",
        "risk_metrics",
        "backtest",
        "kupiec_test",
        "data",
    }
    assert set(results["portfolio"]) == {"tickers", "weights"}
    assert set(results["analysis_period"]) == {
        "start_date",
        "end_date",
        "price_observations",
        "return_observations",
    }
    assert set(results["risk_metrics"]) == {
        "historical_var_95",
        "expected_shortfall_95",
    }


def test_pipeline_retains_intermediate_objects():
    results = run_with_fake()

    data = results["data"]

    assert set(data) == {
        "prices",
        "asset_returns",
        "portfolio_returns",
        "rolling_var",
        "breaches",
    }
    assert isinstance(data["prices"], pd.DataFrame)
    assert isinstance(data["asset_returns"], pd.DataFrame)
    assert isinstance(data["portfolio_returns"], pd.Series)
    assert isinstance(data["rolling_var"], pd.Series)
    assert isinstance(data["breaches"], pd.Series)


def test_risk_metrics_use_builtin_python_types():
    results = run_with_fake()

    metrics = results["risk_metrics"]
    period = results["analysis_period"]

    assert type(metrics["historical_var_95"]) is float
    assert type(metrics["expected_shortfall_95"]) is float
    assert type(period["price_observations"]) is int
    assert type(period["return_observations"]) is int
    assert type(period["start_date"]) is str
    assert type(period["end_date"]) is str
    assert all(type(weight) is float for weight in results["portfolio"]["weights"].values())


def test_analysis_period_counts_match_data():
    prices = make_prices()

    results = run_analysis(provider=FakeProvider(prices))

    assert results["analysis_period"]["price_observations"] == OBSERVATIONS
    assert results["analysis_period"]["return_observations"] == OBSERVATIONS - 1
    assert results["analysis_period"]["start_date"] == "2018-01-02"


def test_rolling_var_preserves_no_lookahead_through_orchestration():
    results = run_with_fake()

    portfolio_returns = results["data"]["portfolio_returns"]
    rolling_var = results["data"]["rolling_var"]

    expected = calculate_rolling_historical_var(
        portfolio_returns,
        window=ROLLING_WINDOW,
        confidence_level=CONFIDENCE_LEVEL,
    )

    pd.testing.assert_series_equal(rolling_var, expected)
    assert rolling_var.iloc[:ROLLING_WINDOW].isna().all()
    assert rolling_var.iloc[ROLLING_WINDOW:].notna().all()


def test_missing_portfolio_returns_fail_explicitly():
    prices = make_prices()
    prices.iloc[300, 0] = np.nan

    with pytest.raises(ValueError, match="Resolve the underlying price gaps"):
        run_analysis(provider=FakeProvider(prices))


def test_missing_portfolio_returns_are_not_silently_dropped():
    prices = make_prices()
    prices.iloc[300, 0] = np.nan

    with pytest.raises(ValueError) as error:
        run_analysis(provider=FakeProvider(prices))

    assert "Portfolio returns contain missing values" in str(error.value)
    assert "will not fill or drop them silently" in str(error.value)


def test_backtest_observations_exclude_rolling_warmup():
    results = run_with_fake()

    backtest = results["backtest"]
    return_observations = results["analysis_period"]["return_observations"]

    assert backtest["observations"] == return_observations - ROLLING_WINDOW
    assert results["data"]["breaches"].isna().sum() == ROLLING_WINDOW


def test_backtest_breach_counts_are_consistent():
    results = run_with_fake()

    backtest = results["backtest"]
    breaches = results["data"]["breaches"]

    assert backtest["breaches"] == int(breaches.dropna().sum())
    assert backtest["breach_rate"] == pytest.approx(
        backtest["breaches"] / backtest["observations"]
    )
    assert backtest["expected_breach_rate"] == pytest.approx(1 - CONFIDENCE_LEVEL)


def test_kupiec_result_is_included_in_output():
    results = run_with_fake()

    kupiec = results["kupiec_test"]

    assert set(kupiec) == {
        "observations",
        "breaches",
        "observed_breach_rate",
        "expected_breach_rate",
        "lr_statistic",
        "p_value",
        "significance_level",
        "reject_null",
    }
    assert kupiec["observations"] == results["backtest"]["observations"]
    assert kupiec["breaches"] == results["backtest"]["breaches"]
    assert kupiec["lr_statistic"] >= 0.0
    assert type(kupiec["reject_null"]) is bool


def test_provider_failure_propagates():
    provider = FakeProvider(error=RuntimeError("provider unavailable"))

    with pytest.raises(RuntimeError, match="provider unavailable"):
        run_analysis(provider=provider)


def test_empty_market_data_fails_validation():
    provider = FakeProvider(pd.DataFrame())

    with pytest.raises(ValueError, match="Market data is empty"):
        run_analysis(provider=provider)


def test_incomplete_market_data_fails_validation():
    prices = make_prices()

    with pytest.raises(ValueError, match="missing tickers"):
        run_analysis(provider=FakeProvider(prices.drop(columns=prices.columns[0])))


def test_pipeline_does_not_call_provider_more_than_once():
    provider = FakeProvider(make_prices())

    run_analysis(provider=provider)

    assert len(provider.calls) == 1
