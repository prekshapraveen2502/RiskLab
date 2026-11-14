import pytest

from src.ai.grounding import (
    ABSOLUTE,
    COMPLEMENT,
    DIRECT,
    PERCENT,
    audit_grounding,
    extract_claims,
    format_grounding_audit,
    is_weak,
    match_claim,
    numeric_fields,
    significant_figures,
)

VALIDATION_EVIDENCE = {
    "evaluated_forecasts": 1926,
    "breaches": 105,
    "observed_breach_rate": 0.05451713395638629,
    "expected_breach_rate": 0.05,
    "kupiec_lr_statistic": 0.8047597435363514,
    "kupiec_p_value": 0.36967408369549404,
    "significance_level": 0.05,
    "reject_null": False,
}

BREACH_EVIDENCE = {
    "total_breaches": 105,
    "returned": 1,
    "limit": 5,
    "breaches": [
        {
            "date": "2020-03-12",
            "portfolio_return": -0.05777857603205594,
            "var_forecast": 0.007414439188204005,
            "loss_threshold": -0.007414439188204005,
            "breach_magnitude": 0.05036413684385194,
        }
    ],
}


def result_with(answer, evidence=None):
    return {
        "answer": answer,
        "tool_calls": [],
        "evidence": evidence
        if evidence is not None
        else [{"tool": "get_model_validation_results", "result": VALIDATION_EVIDENCE}],
        "steps": 2,
    }


def breach_result(answer):
    return result_with(
        answer, [{"tool": "get_var_breach_details", "result": BREACH_EVIDENCE}]
    )


def test_fully_grounded_answer_passes():
    audit = audit_grounding(
        result_with("The Kupiec p-value is 0.3697 and the LR statistic is 0.8048.")
    )

    assert audit["ungrounded"] == 0
    assert audit["grounded"] == 2
    assert audit["is_grounded"] is True


def test_invented_number_is_flagged():
    audit = audit_grounding(result_with("The Kupiec p-value is 0.4213."))

    assert audit["ungrounded"] == 1
    assert audit["is_grounded"] is False
    assert audit["ungrounded_claims"][0]["text"] == "0.4213"


def test_percent_claim_matches_the_decimal_the_tool_returned():
    audit = audit_grounding(result_with("The observed breach rate is 5.45%."))

    claim = audit["grounded_claims"][0]
    assert claim["matched_by"] == PERCENT
    assert claim["source"].endswith("observed_breach_rate")


def test_half_unit_rounding_edge_case():
    # 0.0545171... as a percent is 5.45171...; a claim of 5.45 is within half a
    # unit in the last place (0.005), while 5.46 is not.
    fields = numeric_fields(VALIDATION_EVIDENCE)

    inside = {"value": 5.45, "decimals": 2}
    outside = {"value": 5.46, "decimals": 2}

    assert any(m["kind"] == PERCENT for m in match_claim(inside, fields))
    assert not match_claim(outside, fields)

    # Exactly half a unit away is inside the band, where round() would disagree.
    # 0.05 as a percent is 5.0; a claim of 5.05 to 1 dp sits on the boundary.
    boundary = {"value": 5.05, "decimals": 1}
    assert any(m["kind"] == PERCENT for m in match_claim(boundary, fields))


def test_complement_rule_matches_a_significance_field():
    audit = audit_grounding(
        result_with("Coverage was assessed at the 95% confidence level.")
    )

    # Traceable, but "95" has no decimals, so it is weak rather than strong.
    assert audit["ungrounded"] == 0
    claim = audit["weak_claims"][0]
    assert claim["matched_by"] == COMPLEMENT
    assert "significance_level" in claim["source"]


def test_complement_rule_does_not_apply_to_a_non_significance_field():
    # expected_breach_rate is also 0.05, but its name does not license the
    # one-minus reading, so 95% must not be grounded by it.
    evidence = [
        {
            "tool": "get_model_validation_results",
            "result": {"expected_breach_rate": 0.05, "breaches": 105},
        }
    ]

    audit = audit_grounding(result_with("Coverage was 95% by construction.", evidence))

    assert audit["ungrounded"] == 1
    assert audit["ungrounded_claims"][0]["text"] == "95%"


def test_absolute_value_match_is_recorded_as_such():
    audit = audit_grounding(breach_result("The portfolio took a 5.78% loss that day."))

    claim = audit["grounded_claims"][0]
    assert claim["matched_by"] == ABSOLUTE
    assert claim["source"].endswith("portfolio_return")


def test_signed_claim_prefers_a_direct_reading_over_absolute_value():
    audit = audit_grounding(breach_result("The return was -5.78% on that day."))

    assert audit["grounded_claims"][0]["matched_by"] == PERCENT


def test_low_precision_claim_lands_in_the_weak_bucket():
    audit = audit_grounding(result_with("There were 105 breaches."))

    assert audit["grounded"] == 0
    assert audit["weak"] == 1
    assert audit["ungrounded"] == 0
    assert audit["weak_claims"][0]["text"] == "105"
    # Still reported as traceable, just not counted as strong evidence.
    assert audit["weak_claims"][0]["matched_by"] == DIRECT


def test_claim_records_how_many_distinct_evidence_values_it_matched():
    # At two decimals, "0.05" is within half a unit of both 0.05 and the
    # observed rate 0.0545..., so it is ambiguous between two distinct values.
    # That ambiguity is why a one-significant-figure claim is only ever weak.
    audit = audit_grounding(result_with("The expected rate is 0.05."))

    claim = audit["weak_claims"][0]
    assert claim["matches"] == 2
    assert claim["matched_by"] == DIRECT


def test_dates_are_checked_against_evidence_not_treated_as_numbers():
    audit = audit_grounding(breach_result("The worst breach was on March 12, 2020."))

    assert audit["dates_checked"] == 1
    assert audit["unmatched_dates"] == []
    assert audit["claims"] == 0
    assert audit["masked"]["dates"] >= 1


def test_date_absent_from_evidence_is_flagged():
    audit = audit_grounding(breach_result("A breach occurred on March 13, 2020."))

    assert audit["unmatched_dates"] == ["2020-03-13"]
    assert audit["is_grounded"] is False


def test_section_ordinals_are_masked_only_at_line_start():
    answer = "1. Observed result:\nThe p-value is 0.3697 in test 2. of the suite."
    claims, masked = extract_claims(answer)

    texts = [c["text"] for c in claims]
    assert "0.3697" in texts
    assert masked["ordinals"] == 1
    # The mid-sentence "2." is still inspected rather than silently dropped.
    assert "2" in texts


def test_grounding_is_per_run():
    # A figure from a different tool's output is not grounded by this run.
    audit = audit_grounding(result_with("The breach magnitude was 5.0364%."))

    assert audit["ungrounded"] == 1


def test_empty_evidence_flags_every_number():
    audit = audit_grounding(result_with("The p-value is 0.3697.", []))

    assert audit["claims"] == 1
    assert audit["ungrounded"] == 1
    assert audit["is_grounded"] is False


def test_answer_without_numbers_is_grounded():
    audit = audit_grounding(
        result_with("Coverage was not rejected; clustering remains untested.")
    )

    assert audit["claims"] == 0
    assert audit["is_grounded"] is True


def test_booleans_are_not_treated_as_numbers():
    assert ("reject_null", 0.0) not in numeric_fields(VALIDATION_EVIDENCE)
    assert ("reject_null", 1.0) not in numeric_fields(VALIDATION_EVIDENCE)


def test_numeric_fields_report_nested_key_paths():
    fields = dict(numeric_fields(BREACH_EVIDENCE))

    assert "breaches[0].portfolio_return" in fields
    assert fields["breaches[0].portfolio_return"] == pytest.approx(-0.057778576)


@pytest.mark.parametrize(
    "raw,expected",
    [("5.78", 3), ("0.05", 1), ("105", 3), ("0.3697", 4), ("1,926", 4), ("5", 1)],
)
def test_significant_figures(raw, expected):
    assert significant_figures(raw) == expected


@pytest.mark.parametrize(
    "claim,weak",
    [
        ({"decimals": 0, "significant_figures": 3}, True),
        ({"decimals": 2, "significant_figures": 1}, True),
        ({"decimals": 2, "significant_figures": 3}, False),
    ],
)
def test_weak_classification(claim, weak):
    assert is_weak(claim) is weak


def test_audit_never_modifies_the_answer():
    answer = "The p-value is 0.4213, which is invented."
    result = result_with(answer)

    audit_grounding(result)

    assert result["answer"] == answer
    assert audit_grounding(result)["ungrounded"] == 1


def test_format_names_each_ungrounded_claim():
    audit = audit_grounding(result_with("The p-value is 0.4213."))

    text = format_grounding_audit(audit)

    assert "Ungrounded:         1" in text
    assert "0.4213" in text


def test_decimal_fractions_are_not_masked_as_a_day_list():
    # "0.3, 0.2" must not be read as the day list in "09, 11, and 12 March".
    evidence = [
        {
            "tool": "get_portfolio_risk_overview",
            "result": {"weights": {"SPY": 0.3, "QQQ": 0.2, "GLD": 0.15}},
        }
    ]
    answer = "Weights are 0.3, 0.2, and 0.15 respectively."

    claims, masked = extract_claims(answer)
    audit = audit_grounding(result_with(answer, evidence))

    assert [c["text"] for c in claims] == ["0.3", "0.2", "0.15"]
    assert masked["dates"] == 0
    assert audit["ungrounded"] == 0


def test_day_list_is_still_masked():
    answer = "Breaches fell on 09, 11, 12, 16, and 18 March."

    claims, masked = extract_claims(answer)

    assert masked["dates"] >= 1
    assert claims == []
