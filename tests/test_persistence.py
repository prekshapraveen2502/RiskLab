import copy
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

import run_pipeline
from run_pipeline import (
    ROLLING_WINDOW,
    SUMMARY_SECTIONS,
    build_risk_summary,
    output_paths,
    run_analysis,
    save_analysis_outputs,
)
from test_pipeline import FakeProvider, make_prices


@pytest.fixture
def results():
    return run_analysis(provider=FakeProvider(make_prices()))


@pytest.fixture
def saved(results, tmp_path):
    save_analysis_outputs(results, data_dir=tmp_path)
    return results, output_paths(tmp_path)


def snapshot(root):
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_all_six_outputs_are_created(saved, tmp_path):
    _, paths = saved

    assert len(paths) == 6
    for path in paths.values():
        assert path.exists()
        assert path.stat().st_size > 0

    assert paths["prices"] == tmp_path / "raw" / "prices.parquet"
    assert paths["asset_returns"] == tmp_path / "processed" / "asset_returns.parquet"
    assert (
        paths["portfolio_returns"] == tmp_path / "processed" / "portfolio_returns.parquet"
    )
    assert (
        paths["rolling_var"]
        == tmp_path / "processed" / "rolling_historical_var.parquet"
    )
    assert paths["breaches"] == tmp_path / "processed" / "var_breaches.parquet"
    assert paths["risk_summary"] == tmp_path / "processed" / "risk_summary.json"


def test_risk_summary_json_loads(saved):
    _, paths = saved

    summary = json.loads(paths["risk_summary"].read_text())

    assert isinstance(summary, dict)


def test_risk_summary_excludes_in_memory_data(saved):
    _, paths = saved

    raw = paths["risk_summary"].read_text()
    summary = json.loads(raw)

    assert "data" not in summary
    assert "prices" not in raw


def test_risk_summary_contains_exactly_required_sections(saved):
    _, paths = saved

    summary = json.loads(paths["risk_summary"].read_text())

    assert set(summary) == set(SUMMARY_SECTIONS)
    assert len(summary) == 5


def test_risk_summary_has_no_nan_or_infinity(saved):
    _, paths = saved

    raw = paths["risk_summary"].read_text()

    assert "NaN" not in raw
    assert "Infinity" not in raw


def test_risk_summary_uses_json_scalar_types(saved):
    results, paths = saved

    raw = paths["risk_summary"].read_text()
    summary = json.loads(raw)

    assert type(summary["analysis_period"]["return_observations"]) is int
    assert type(summary["risk_metrics"]["historical_var_95"]) is float
    assert type(summary["backtest"]["observations"]) is int
    assert type(summary["kupiec_test"]["reject_null"]) is bool
    assert summary == build_risk_summary(results)

    expected_boolean = "true" if summary["kupiec_test"]["reject_null"] else "false"
    assert f'"reject_null": {expected_boolean}' in raw


def test_risk_summary_is_indented(saved):
    _, paths = saved

    raw = paths["risk_summary"].read_text()

    assert '\n  "portfolio": {' in raw


def test_portfolio_returns_round_trip_preserves_datetime_index(saved):
    results, paths = saved

    original = results["data"]["portfolio_returns"]
    restored = pd.read_parquet(paths["portfolio_returns"])["portfolio_return"]

    assert isinstance(restored.index, pd.DatetimeIndex)
    assert restored.name == "portfolio_return"
    pd.testing.assert_index_equal(restored.index, original.index, exact=True)
    # Parquet does not persist the index freq attribute; real market data has none.
    pd.testing.assert_series_equal(restored, original, check_freq=False)


def test_prices_and_asset_returns_round_trip(saved):
    results, paths = saved

    restored_prices = pd.read_parquet(paths["prices"])
    restored_returns = pd.read_parquet(paths["asset_returns"])

    assert isinstance(restored_prices.index, pd.DatetimeIndex)
    assert list(restored_prices.columns) == results["portfolio"]["tickers"]
    pd.testing.assert_frame_equal(
        restored_prices, results["data"]["prices"], check_freq=False
    )
    pd.testing.assert_frame_equal(
        restored_returns, results["data"]["asset_returns"], check_freq=False
    )


def test_rolling_var_round_trip_preserves_warmup_gaps(saved):
    results, paths = saved

    original = results["data"]["rolling_var"]
    restored = pd.read_parquet(paths["rolling_var"])["historical_var"]

    assert restored.isna().sum() == ROLLING_WINDOW
    assert restored.iloc[:ROLLING_WINDOW].isna().all()
    assert restored.iloc[ROLLING_WINDOW:].notna().all()
    assert restored.name == "historical_var"
    pd.testing.assert_series_equal(restored, original, check_freq=False)


def test_breach_round_trip_preserves_nullable_semantics(saved):
    results, paths = saved

    original = results["data"]["breaches"]
    restored = pd.read_parquet(paths["breaches"])["var_breach"]

    assert isinstance(restored.dtype, pd.BooleanDtype)
    assert restored.name == "var_breach"
    pd.testing.assert_series_equal(restored, original, check_freq=False)

    assert restored.isna().sum() == original.isna().sum()
    assert (restored == True).sum() == (original == True).sum()
    assert (restored == False).sum() == (original == False).sum()

    warmup = restored.iloc[:ROLLING_WINDOW]
    assert warmup.isna().all()
    assert not (warmup == False).any()

    evaluated = restored.iloc[ROLLING_WINDOW:]
    assert evaluated.notna().all()
    assert (evaluated == True).any()
    assert (evaluated == False).any()


def test_saving_does_not_mutate_results(results, tmp_path):
    expected_summary = copy.deepcopy(build_risk_summary(results))
    original_keys = set(results)
    original_data = {
        name: value.copy() for name, value in results["data"].items()
    }

    save_analysis_outputs(results, data_dir=tmp_path)

    assert set(results) == original_keys
    assert "data" in results
    assert build_risk_summary(results) == expected_summary

    pd.testing.assert_frame_equal(results["data"]["prices"], original_data["prices"])
    pd.testing.assert_frame_equal(
        results["data"]["asset_returns"], original_data["asset_returns"]
    )
    pd.testing.assert_series_equal(
        results["data"]["portfolio_returns"], original_data["portfolio_returns"]
    )
    pd.testing.assert_series_equal(
        results["data"]["rolling_var"], original_data["rolling_var"]
    )
    pd.testing.assert_series_equal(
        results["data"]["breaches"], original_data["breaches"]
    )


def test_saving_creates_missing_directories(results, tmp_path):
    data_dir = tmp_path / "nested" / "data"

    save_analysis_outputs(results, data_dir=data_dir)

    for path in output_paths(data_dir).values():
        assert path.exists()


def test_importing_run_pipeline_writes_nothing():
    repo_root = Path(run_pipeline.__file__).parent
    data_dir = repo_root / "data"
    before = snapshot(data_dir)

    completed = subprocess.run(
        [sys.executable, "-c", "import run_pipeline"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert snapshot(data_dir) == before


def test_output_confirmation_lists_every_output(tmp_path):
    confirmation = run_pipeline.format_output_confirmation(tmp_path / "data")

    for path in output_paths(tmp_path / "data").values():
        assert path.name in confirmation
