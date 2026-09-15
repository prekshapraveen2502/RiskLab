import math

import pandas as pd
import pytest

from src.risk.backtesting import (
    detect_var_breaches,
    kupiec_unconditional_coverage_test,
    summarize_var_backtest,
)

DATES = pd.to_datetime(
    ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]
)


def make_returns():
    return pd.Series([-0.01, -0.02, -0.04, 0.01], index=DATES, name="portfolio_return")


def make_forecasts():
    return pd.Series([None, 0.025, 0.025, 0.025], index=DATES, name="historical_var")


def test_detect_var_breaches_returns_expected_states():
    expected = pd.Series(
        [pd.NA, False, True, False],
        index=DATES,
        dtype="boolean",
        name="var_breach",
    )

    breaches = detect_var_breaches(make_returns(), make_forecasts())

    pd.testing.assert_series_equal(breaches, expected)


def test_missing_var_forecast_is_not_evaluated():
    breaches = detect_var_breaches(make_returns(), make_forecasts())

    assert pd.isna(breaches.iloc[0])
    assert breaches.iloc[0] is not False
    assert breaches.isna().sum() == 1


def test_loss_equal_to_var_is_not_a_breach():
    dates = DATES[:1]
    returns = pd.Series([-0.025], index=dates, name="portfolio_return")
    forecasts = pd.Series([0.025], index=dates, name="historical_var")

    breaches = detect_var_breaches(returns, forecasts)

    assert breaches.iloc[0] == False


def test_loss_worse_than_var_is_a_breach():
    dates = DATES[:1]
    returns = pd.Series([-0.026], index=dates, name="portfolio_return")
    forecasts = pd.Series([0.025], index=dates, name="historical_var")

    breaches = detect_var_breaches(returns, forecasts)

    assert breaches.iloc[0] == True


def test_matching_indexes_are_required():
    forecasts = make_forecasts()
    forecasts.index = pd.to_datetime(
        ["2025-02-03", "2025-02-04", "2025-02-05", "2025-02-06"]
    )

    with pytest.raises(ValueError, match="matching indexes"):
        detect_var_breaches(make_returns(), forecasts)


def test_missing_portfolio_return_fails():
    returns = pd.Series([-0.01, None, -0.04, 0.01], index=DATES)

    with pytest.raises(ValueError, match="missing values"):
        detect_var_breaches(returns, make_forecasts())


def test_breach_output_metadata():
    returns = make_returns()

    breaches = detect_var_breaches(returns, make_forecasts())

    assert isinstance(breaches.dtype, pd.BooleanDtype)
    assert breaches.name == "var_breach"
    pd.testing.assert_index_equal(breaches.index, returns.index)


def test_detect_var_breaches_does_not_modify_inputs():
    returns = make_returns()
    forecasts = make_forecasts()
    original_returns = returns.copy()
    original_forecasts = forecasts.copy()

    detect_var_breaches(returns, forecasts)

    pd.testing.assert_series_equal(returns, original_returns)
    pd.testing.assert_series_equal(forecasts, original_forecasts)


def make_breaches(values):
    return pd.Series(values, dtype="boolean", name="var_breach")


def test_summarize_var_backtest_returns_expected_metrics():
    breaches = make_breaches([pd.NA, False, True, False, True, pd.NA, False])

    summary = summarize_var_backtest(breaches)

    assert summary == {
        "observations": 5,
        "breaches": 2,
        "breach_rate": pytest.approx(0.4),
        "expected_breach_rate": pytest.approx(0.05),
    }


def test_missing_forecasts_are_excluded_from_denominator():
    evaluated_only = make_breaches([False, True, False, True, False])
    with_missing = make_breaches([pd.NA, False, True, False, True, pd.NA, False])

    assert summarize_var_backtest(with_missing) == summarize_var_backtest(evaluated_only)
    assert summarize_var_backtest(with_missing)["observations"] == 5


def test_summary_without_breaches():
    breaches = make_breaches([pd.NA, False, False, False])

    summary = summarize_var_backtest(breaches)

    assert summary["observations"] == 3
    assert summary["breaches"] == 0
    assert summary["breach_rate"] == 0.0


def test_summary_when_all_evaluated_observations_breach():
    breaches = make_breaches([pd.NA, True, True, True])

    summary = summarize_var_backtest(breaches)

    assert summary["observations"] == 3
    assert summary["breaches"] == 3
    assert summary["breach_rate"] == 1.0


def test_summary_requires_evaluated_forecasts():
    breaches = make_breaches([pd.NA, pd.NA, pd.NA])

    with pytest.raises(ValueError, match="No evaluated VaR forecasts available"):
        summarize_var_backtest(breaches)


@pytest.mark.parametrize("confidence_level", [0, 1, -0.10, 1.10])
def test_summary_rejects_invalid_confidence_levels(confidence_level):
    breaches = make_breaches([False, True, False])

    with pytest.raises(ValueError, match="Confidence level must be between 0 and 1"):
        summarize_var_backtest(breaches, confidence_level=confidence_level)


def test_summary_uses_custom_confidence_level():
    breaches = make_breaches([False, True, False, False])

    summary = summarize_var_backtest(breaches, confidence_level=0.99)

    assert summary["expected_breach_rate"] == pytest.approx(0.01)


def test_summary_uses_builtin_python_types():
    breaches = make_breaches([pd.NA, False, True, False, True, pd.NA, False])

    summary = summarize_var_backtest(breaches)

    assert type(summary["observations"]) is int
    assert type(summary["breaches"]) is int
    assert type(summary["breach_rate"]) is float
    assert type(summary["expected_breach_rate"]) is float


def make_breach_sample(observations, breach_count, warmup=0):
    values = (
        [pd.NA] * warmup
        + [True] * breach_count
        + [False] * (observations - breach_count)
    )
    return make_breaches(values)


def test_kupiec_accepts_exact_expected_coverage():
    result = kupiec_unconditional_coverage_test(make_breach_sample(100, 5))

    assert result["observations"] == 100
    assert result["breaches"] == 5
    assert result["observed_breach_rate"] == pytest.approx(0.05)
    assert result["expected_breach_rate"] == pytest.approx(0.05)
    assert result["lr_statistic"] == pytest.approx(0.0)
    assert result["lr_statistic"] >= 0.0
    assert result["p_value"] == pytest.approx(1.0)
    assert result["reject_null"] is False


def test_kupiec_rejects_excessive_breaches():
    result = kupiec_unconditional_coverage_test(make_breach_sample(100, 12))

    assert result["observations"] == 100
    assert result["breaches"] == 12
    assert result["observed_breach_rate"] == pytest.approx(0.12)
    assert result["lr_statistic"] == pytest.approx(7.5401961229627545)
    assert result["p_value"] == pytest.approx(0.006033747461594096)
    assert result["reject_null"] is True


def test_kupiec_does_not_reject_moderate_deviation():
    result = kupiec_unconditional_coverage_test(make_breach_sample(100, 8))

    assert result["observations"] == 100
    assert result["breaches"] == 8
    assert result["lr_statistic"] == pytest.approx(1.615808190455681)
    assert result["p_value"] == pytest.approx(0.2036772675975769)
    assert result["reject_null"] is False


def test_kupiec_handles_zero_breaches():
    result = kupiec_unconditional_coverage_test(make_breach_sample(100, 0))

    assert result["breaches"] == 0
    assert result["observed_breach_rate"] == 0.0
    assert math.isfinite(result["lr_statistic"])
    assert result["lr_statistic"] == pytest.approx(10.258658877510115)
    assert result["p_value"] == pytest.approx(0.0013604454302787966)
    assert result["reject_null"] is True


def test_kupiec_handles_all_breaches():
    result = kupiec_unconditional_coverage_test(make_breach_sample(5, 5))

    assert result["observations"] == 5
    assert result["breaches"] == 5
    assert result["observed_breach_rate"] == 1.0
    assert math.isfinite(result["lr_statistic"])
    assert math.isfinite(result["p_value"])
    assert result["lr_statistic"] == pytest.approx(29.9573227355399)


def test_kupiec_excludes_warmup_observations():
    warmed = kupiec_unconditional_coverage_test(make_breach_sample(100, 5, warmup=25))

    assert warmed["observations"] == 100
    assert warmed == kupiec_unconditional_coverage_test(make_breach_sample(100, 5))


def test_kupiec_significance_level_changes_only_the_decision():
    breaches = make_breach_sample(100, 8)

    strict = kupiec_unconditional_coverage_test(breaches, significance_level=0.05)
    lenient = kupiec_unconditional_coverage_test(breaches, significance_level=0.25)

    assert strict["lr_statistic"] == lenient["lr_statistic"]
    assert strict["p_value"] == lenient["p_value"]
    assert strict["significance_level"] == pytest.approx(0.05)
    assert lenient["significance_level"] == pytest.approx(0.25)
    assert strict["reject_null"] is False
    assert lenient["reject_null"] is True


@pytest.mark.parametrize("significance_level", [0, 1, -0.10, 1.10])
def test_kupiec_rejects_invalid_significance_levels(significance_level):
    breaches = make_breach_sample(100, 5)

    with pytest.raises(ValueError, match="Significance level must be between 0 and 1"):
        kupiec_unconditional_coverage_test(
            breaches, significance_level=significance_level
        )


@pytest.mark.parametrize("confidence_level", [0, 1, -0.10, 1.10])
def test_kupiec_rejects_invalid_confidence_levels(confidence_level):
    breaches = make_breach_sample(100, 5)

    with pytest.raises(ValueError, match="Confidence level must be between 0 and 1"):
        kupiec_unconditional_coverage_test(breaches, confidence_level=confidence_level)


def test_kupiec_uses_custom_confidence_level():
    result = kupiec_unconditional_coverage_test(
        make_breach_sample(100, 5), confidence_level=0.99
    )

    assert result["expected_breach_rate"] == pytest.approx(0.01)
    assert result["observed_breach_rate"] == pytest.approx(0.05)
    assert result["reject_null"] is True


def test_kupiec_requires_evaluated_forecasts():
    breaches = make_breaches([pd.NA, pd.NA, pd.NA])

    with pytest.raises(ValueError, match="No evaluated VaR forecasts available"):
        kupiec_unconditional_coverage_test(breaches)


def test_kupiec_uses_builtin_python_types():
    result = kupiec_unconditional_coverage_test(make_breach_sample(100, 8))

    assert type(result["observations"]) is int
    assert type(result["breaches"]) is int
    assert type(result["observed_breach_rate"]) is float
    assert type(result["expected_breach_rate"]) is float
    assert type(result["lr_statistic"]) is float
    assert type(result["p_value"]) is float
    assert type(result["significance_level"]) is float
    assert type(result["reject_null"]) is bool
