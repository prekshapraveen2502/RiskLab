import json
import re

import pytest

from src.ai import tools
from src.ai.reporting import build_deterministic_validation_report

BASE_SUMMARY = {
    "portfolio": {
        "tickers": ["SPY", "TLT"],
        "weights": {"SPY": 0.6, "TLT": 0.4},
    },
    "analysis_period": {
        "start_date": "2019-01-02",
        "end_date": "2024-12-31",
        "price_observations": 1001,
        "return_observations": 1000,
    },
    "risk_metrics": {
        "historical_var_95": 0.0125,
        "expected_shortfall_95": 0.0189,
    },
    "backtest": {
        "observations": 750,
        "breaches": 40,
        "breach_rate": 0.05333333333333334,
        "expected_breach_rate": 0.05,
    },
    "kupiec_test": {
        "observations": 750,
        "breaches": 40,
        "observed_breach_rate": 0.05333333333333334,
        "expected_breach_rate": 0.05,
        "lr_statistic": 0.17123456789,
        "p_value": 0.6790123456,
        "significance_level": 0.05,
        "reject_null": False,
    },
}

# Phrases that are never acceptable in any context.
FORBIDDEN_CLAIMS = (
    "proven correct",
    "fully validated",
    "confirms the model",
    "model is accurate",
)

# Correctness claims are only acceptable when negated, e.g. "not evidence that the
# model is correct". This finds affirmative uses without banning the disclaimers.
CORRECTNESS_PATTERN = re.compile(
    r"(?:var )?model is (?:correct|proven|validated|verified|valid)"
)
NEGATIONS = ("not ", "cannot ", "never ", "no ", "n't ")


def affirmative_correctness_claims(report):
    lowered = report.lower()
    claims = []

    for match in CORRECTNESS_PATTERN.finditer(lowered):
        prefix = lowered[max(0, match.start() - 80) : match.start()]
        if not any(negation in prefix for negation in NEGATIONS):
            claims.append(match.group(0))

    return claims


def make_summary(**overrides):
    summary = json.loads(json.dumps(BASE_SUMMARY))
    for section, values in overrides.items():
        summary[section].update(values)
    return summary


def test_report_contains_required_sections():
    report = build_deterministic_validation_report(make_summary())

    assert "PORTFOLIO SCOPE" in report
    assert "RISK METRICS" in report
    assert "BACKTEST VALIDATION" in report
    assert "STATISTICAL INTERPRETATION" in report
    assert "LIMITATIONS" in report


def test_report_includes_supplied_metrics_with_percentage_formatting():
    report = build_deterministic_validation_report(make_summary())

    assert "1.2500%" in report
    assert "1.8900%" in report
    assert "5.3333%" in report
    assert "5.0000%" in report
    assert "0.171235" in report
    assert "0.679012" in report
    assert "5.00%" in report
    assert "750" in report
    assert "40" in report
    assert "SPY 60.00%" in report
    assert "TLT 40.00%" in report


def test_report_uses_only_supplied_values():
    summary = make_summary(
        risk_metrics={"historical_var_95": 0.02, "expected_shortfall_95": 0.03}
    )

    report = build_deterministic_validation_report(summary)

    assert "2.0000%" in report
    assert "3.0000%" in report
    assert "1.2500%" not in report


def test_non_rejection_interpretation_is_correct():
    report = build_deterministic_validation_report(make_summary())

    assert "does not reject the null hypothesis" in report
    assert "not evidence that the model is correct" in report
    assert "Reject Null:          False" in report


def test_rejection_interpretation_is_correct():
    summary = make_summary(
        kupiec_test={"reject_null": True, "p_value": 0.004, "lr_statistic": 8.1}
    )

    report = build_deterministic_validation_report(summary)

    assert "rejects the null hypothesis" in report
    assert "statistically" in report
    assert "inconsistent with the expected unconditional coverage" in report
    assert "Reject Null:          True" in report


@pytest.mark.parametrize("reject_null", [False, True])
def test_report_never_claims_proof_or_correctness(reject_null):
    summary = make_summary(kupiec_test={"reject_null": reject_null})

    report = build_deterministic_validation_report(summary)

    for claim in FORBIDDEN_CLAIMS:
        assert claim not in report.lower()

    assert affirmative_correctness_claims(report) == []


def test_correctness_detector_catches_affirmative_claims():
    assert affirmative_correctness_claims("The model is correct.") == [
        "model is correct"
    ]
    assert affirmative_correctness_claims("This proves the model is validated.") == [
        "model is validated"
    ]
    assert affirmative_correctness_claims("It is not evidence that the model is correct.") == []
    assert affirmative_correctness_claims("We cannot establish that a var model is correct.") == []


def test_report_states_limitations():
    report = build_deterministic_validation_report(make_summary()).lower()

    assert "cannot establish that a var model is correct" in report
    assert "does not test breach independence" in report
    assert "clustering" in report
    assert "historical sample represents future" in report
    assert "unstable" in report


@pytest.mark.skipif(
    not tools.RISK_SUMMARY_PATH.exists(),
    reason="risk_summary.json missing; run run_pipeline.py",
)
def test_report_builds_from_real_persisted_summary():
    summary = json.loads(tools.RISK_SUMMARY_PATH.read_text())

    report = build_deterministic_validation_report(summary)

    assert str(summary["backtest"]["observations"]) in report
    assert str(summary["backtest"]["breaches"]) in report
    for claim in FORBIDDEN_CLAIMS:
        assert claim not in report.lower()

    assert affirmative_correctness_claims(report) == []
