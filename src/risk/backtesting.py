from math import log

import pandas as pd
from scipy.stats import chi2


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


def _binomial_log_likelihood(
    observations: int,
    breach_count: int,
    breach_probability: float,
) -> float:
    non_breach_count = observations - breach_count

    breach_term = breach_count * log(breach_probability) if breach_count else 0.0
    non_breach_term = (
        non_breach_count * log(1 - breach_probability) if non_breach_count else 0.0
    )

    return breach_term + non_breach_term


def kupiec_unconditional_coverage_test(
    breaches: pd.Series,
    confidence_level: float = 0.95,
    significance_level: float = 0.05,
) -> dict:
    if not 0 < significance_level < 1:
        raise ValueError("Significance level must be between 0 and 1")

    summary = summarize_var_backtest(breaches, confidence_level=confidence_level)

    observations = summary["observations"]
    breach_count = summary["breaches"]
    observed_breach_rate = summary["breach_rate"]
    expected_breach_rate = summary["expected_breach_rate"]

    log_likelihood_null = _binomial_log_likelihood(
        observations, breach_count, expected_breach_rate
    )
    log_likelihood_unrestricted = _binomial_log_likelihood(
        observations, breach_count, observed_breach_rate
    )

    lr_statistic = 2 * (log_likelihood_unrestricted - log_likelihood_null)
    lr_statistic = max(float(lr_statistic), 0.0)
    p_value = float(chi2.sf(lr_statistic, df=1))

    return {
        "observations": observations,
        "breaches": breach_count,
        "observed_breach_rate": observed_breach_rate,
        "expected_breach_rate": expected_breach_rate,
        "lr_statistic": lr_statistic,
        "p_value": p_value,
        "significance_level": float(significance_level),
        "reject_null": bool(p_value < significance_level),
    }