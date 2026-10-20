import json

import pandas as pd
import pytest

from src.ai import tools
from src.ai.tools import (
    MAX_LIMIT,
    TOOL_REGISTRY,
    execute_tool,
    get_model_validation_results,
    get_period_risk_snapshot,
    get_portfolio_risk_overview,
    get_var_breach_details,
    get_worst_portfolio_days,
    tool_schemas,
)

PARQUET_PATHS = (
    tools.PORTFOLIO_RETURNS_PATH,
    tools.ROLLING_VAR_PATH,
    tools.BREACHES_PATH,
)

requires_parquet = pytest.mark.skipif(
    not all(path.exists() for path in PARQUET_PATHS),
    reason="Parquet outputs are gitignored; run run_pipeline.py to generate them",
)

requires_summary = pytest.mark.skipif(
    not tools.RISK_SUMMARY_PATH.exists(),
    reason="risk_summary.json missing; run run_pipeline.py",
)


def persisted_summary():
    return json.loads(tools.RISK_SUMMARY_PATH.read_text())


def snapshot_files():
    return {
        str(path): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in (*PARQUET_PATHS, tools.RISK_SUMMARY_PATH)
        if path.exists()
    }


@requires_summary
def test_portfolio_overview_reads_persisted_values():
    summary = persisted_summary()

    overview = get_portfolio_risk_overview()

    assert overview["tickers"] == summary["portfolio"]["tickers"]
    assert overview["weights"] == summary["portfolio"]["weights"]
    assert overview["analysis_start_date"] == summary["analysis_period"]["start_date"]
    assert overview["analysis_end_date"] == summary["analysis_period"]["end_date"]
    assert (
        overview["return_observations"]
        == summary["analysis_period"]["return_observations"]
    )
    assert overview["historical_var_95"] == summary["risk_metrics"]["historical_var_95"]
    assert (
        overview["expected_shortfall_95"]
        == summary["risk_metrics"]["expected_shortfall_95"]
    )


@requires_summary
def test_validation_results_read_persisted_kupiec_values():
    summary = persisted_summary()
    backtest = summary["backtest"]
    kupiec = summary["kupiec_test"]

    results = get_model_validation_results()

    assert results["evaluated_forecasts"] == backtest["observations"]
    assert results["breaches"] == backtest["breaches"]
    assert results["observed_breach_rate"] == backtest["breach_rate"]
    assert results["expected_breach_rate"] == backtest["expected_breach_rate"]
    assert results["kupiec_lr_statistic"] == kupiec["lr_statistic"]
    assert results["kupiec_p_value"] == kupiec["p_value"]
    assert results["significance_level"] == kupiec["significance_level"]
    assert results["reject_null"] == kupiec["reject_null"]


@requires_parquet
def test_breach_details_return_only_true_breach_rows():
    breaches = pd.read_parquet(tools.BREACHES_PATH)["var_breach"]
    expected_dates = {
        date.strftime("%Y-%m-%d") for date in breaches[breaches == True].index
    }

    details = get_var_breach_details(limit=MAX_LIMIT)

    assert details["total_breaches"] == len(expected_dates)
    returned_dates = {row["date"] for row in details["breaches"]}
    assert returned_dates <= expected_dates

    na_dates = {date.strftime("%Y-%m-%d") for date in breaches[breaches.isna()].index}
    false_dates = {
        date.strftime("%Y-%m-%d") for date in breaches[breaches == False].index
    }
    assert not returned_dates & na_dates
    assert not returned_dates & false_dates


@requires_parquet
def test_breach_details_are_sorted_by_descending_magnitude():
    details = get_var_breach_details(limit=25)

    magnitudes = [row["breach_magnitude"] for row in details["breaches"]]

    assert magnitudes == sorted(magnitudes, reverse=True)
    assert all(magnitude > 0 for magnitude in magnitudes)


@requires_parquet
def test_breach_magnitude_is_deterministic():
    portfolio_returns = pd.read_parquet(tools.PORTFOLIO_RETURNS_PATH)["portfolio_return"]
    rolling_var = pd.read_parquet(tools.ROLLING_VAR_PATH)["historical_var"]

    details = get_var_breach_details(limit=10)

    for row in details["breaches"]:
        date = pd.Timestamp(row["date"])
        expected_return = float(portfolio_returns.loc[date])
        expected_var = float(rolling_var.loc[date])

        assert row["portfolio_return"] == expected_return
        assert row["var_forecast"] == expected_var
        assert row["loss_threshold"] == -expected_var
        assert row["breach_magnitude"] == pytest.approx(
            (-expected_return) - expected_var
        )
        # A breach means the realised loss exceeded the forecast loss threshold.
        assert expected_return < -expected_var


@requires_parquet
def test_worst_portfolio_days_are_ordered_worst_first():
    portfolio_returns = pd.read_parquet(tools.PORTFOLIO_RETURNS_PATH)["portfolio_return"]
    expected = portfolio_returns.sort_values().head(5)

    worst = get_worst_portfolio_days(limit=5)

    returns = [row["portfolio_return"] for row in worst["worst_days"]]
    assert returns == sorted(returns)
    assert returns == [float(value) for value in expected]
    assert [row["date"] for row in worst["worst_days"]] == [
        date.strftime("%Y-%m-%d") for date in expected.index
    ]


@requires_parquet
@pytest.mark.parametrize("limit", [0, -1, -100])
def test_limit_must_be_positive(limit):
    with pytest.raises(ValueError, match="positive integer"):
        get_var_breach_details(limit=limit)

    with pytest.raises(ValueError, match="positive integer"):
        get_worst_portfolio_days(limit=limit)


@requires_parquet
@pytest.mark.parametrize("limit", ["10", 10.5, None, True])
def test_limit_must_be_an_integer(limit):
    with pytest.raises(ValueError, match="must be an integer"):
        get_var_breach_details(limit=limit)


@requires_parquet
def test_limit_is_capped_at_maximum():
    details = get_var_breach_details(limit=10_000)

    assert details["limit"] == MAX_LIMIT
    assert len(details["breaches"]) <= MAX_LIMIT

    worst = get_worst_portfolio_days(limit=10_000)
    assert worst["limit"] == MAX_LIMIT
    assert len(worst["worst_days"]) <= MAX_LIMIT


@requires_parquet
def test_period_snapshot_returns_requested_range():
    snapshot = get_period_risk_snapshot("2020-03-01", "2020-03-31")

    assert snapshot["observations"] > 0
    assert snapshot["start_date"] == "2020-03-01"
    assert snapshot["end_date"] == "2020-03-31"

    dates = [row["date"] for row in snapshot["rows"]]
    assert dates == sorted(dates)
    assert all("2020-03-01" <= date <= "2020-03-31" for date in dates)

    for row in snapshot["rows"]:
        assert set(row) == {"date", "portfolio_return", "rolling_var", "var_breach"}


@requires_parquet
def test_period_snapshot_rejects_invalid_ranges():
    with pytest.raises(ValueError, match="must not be after"):
        get_period_risk_snapshot("2021-01-01", "2020-01-01")

    with pytest.raises(ValueError, match="must be a string"):
        get_period_risk_snapshot(2020, "2020-01-01")


@requires_parquet
def test_tools_do_not_modify_persisted_files():
    before = snapshot_files()

    get_portfolio_risk_overview()
    get_model_validation_results()
    get_var_breach_details(limit=5)
    get_worst_portfolio_days(limit=5)
    get_period_risk_snapshot("2020-01-01", "2020-12-31")

    assert snapshot_files() == before


@requires_parquet
def test_tool_outputs_are_json_serializable_scalars():
    results = [
        get_portfolio_risk_overview(),
        get_model_validation_results(),
        get_var_breach_details(limit=3),
        get_worst_portfolio_days(limit=3),
        get_period_risk_snapshot("2020-03-01", "2020-03-10"),
    ]

    for result in results:
        # allow_nan=False rejects NaN/Infinity, which are not valid JSON.
        json.dumps(result, allow_nan=False)

    validation = results[1]
    assert type(validation["evaluated_forecasts"]) is int
    assert type(validation["breaches"]) is int
    assert type(validation["observed_breach_rate"]) is float
    assert type(validation["reject_null"]) is bool

    breach_row = results[2]["breaches"][0]
    assert type(breach_row["date"]) is str
    assert type(breach_row["portfolio_return"]) is float
    assert type(breach_row["breach_magnitude"]) is float


def test_registry_entries_are_complete():
    assert set(TOOL_REGISTRY) == {
        "get_portfolio_risk_overview",
        "get_model_validation_results",
        "get_var_breach_details",
        "get_worst_portfolio_days",
        "get_period_risk_snapshot",
    }

    for name, entry in TOOL_REGISTRY.items():
        assert set(entry) == {"description", "parameters", "function"}
        assert callable(entry["function"])
        assert len(entry["description"]) > 40
        assert "Use this" in entry["description"]

        parameters = entry["parameters"]
        assert parameters["type"] == "object"
        assert parameters["additionalProperties"] is False
        assert set(parameters["required"]) == set(parameters["properties"])


def test_tool_schemas_expose_only_registered_tools():
    schemas = tool_schemas()

    assert [schema["name"] for schema in schemas] == list(TOOL_REGISTRY)
    for schema in schemas:
        assert set(schema) == {"name", "description", "parameters"}


def test_execute_tool_rejects_unknown_tool():
    with pytest.raises(ValueError, match="Unknown tool: run_python"):
        execute_tool("run_python", {"code": "print(1)"})


@requires_summary
def test_execute_tool_rejects_unexpected_arguments():
    with pytest.raises(ValueError, match="unexpected arguments"):
        execute_tool("get_model_validation_results", {"limit": 5})


@requires_parquet
def test_execute_tool_runs_registered_tool():
    assert execute_tool("get_var_breach_details", {"limit": 2}) == (
        get_var_breach_details(limit=2)
    )
