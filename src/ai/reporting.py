def build_deterministic_validation_report(summary: dict) -> str:
    portfolio = summary["portfolio"]
    period = summary["analysis_period"]
    metrics = summary["risk_metrics"]
    backtest = summary["backtest"]
    kupiec = summary["kupiec_test"]

    weights = ", ".join(
        f"{ticker} {weight:.2%}" for ticker, weight in portfolio["weights"].items()
    )

    reject_null = bool(kupiec["reject_null"])
    significance = float(kupiec["significance_level"])

    if reject_null:
        interpretation = (
            f"The Kupiec unconditional coverage test rejects the null hypothesis at "
            f"the {significance:.0%} significance level. The observed breach "
            f"frequency of {backtest['breach_rate']:.4%} is statistically "
            f"inconsistent with the expected unconditional coverage of "
            f"{backtest['expected_breach_rate']:.4%}."
        )
    else:
        interpretation = (
            f"The Kupiec unconditional coverage test does not reject the null "
            f"hypothesis at the {significance:.0%} significance level. This means "
            f"only that unconditional coverage was not rejected; it is not evidence "
            f"that the model is correct."
        )

    lines = [
        "RiskLab Deterministic Validation Report",
        "=" * 39,
        "",
        "PORTFOLIO SCOPE",
        f"  Tickers:              {', '.join(portfolio['tickers'])}",
        f"  Weights:              {weights}",
        f"  Analysis Period:      {period['start_date']} to {period['end_date']}",
        f"  Return Observations:  {period['return_observations']}",
        "",
        "RISK METRICS",
        f"  Historical VaR (95%): {metrics['historical_var_95']:.4%}",
        f"  Expected Shortfall:   {metrics['expected_shortfall_95']:.4%}",
        "",
        "BACKTEST VALIDATION",
        f"  Evaluated Forecasts:  {backtest['observations']}",
        f"  Breaches:             {backtest['breaches']}",
        f"  Observed Breach Rate: {backtest['breach_rate']:.4%}",
        f"  Expected Breach Rate: {backtest['expected_breach_rate']:.4%}",
        f"  Kupiec LR Statistic:  {kupiec['lr_statistic']:.6f}",
        f"  Kupiec p-value:       {kupiec['p_value']:.6f}",
        f"  Significance Level:   {significance:.2%}",
        f"  Reject Null:          {reject_null}",
        "",
        "STATISTICAL INTERPRETATION",
        f"  {interpretation}",
        "",
        "LIMITATIONS",
        "  - Statistical backtesting cannot establish that a VaR model is correct.",
        "  - Kupiec unconditional coverage does not test breach independence, so it",
        "    cannot detect breach clustering in time.",
        "  - Historical VaR assumes the historical sample represents future",
        "    conditions.",
        "  - Expected Shortfall is estimated from few tail observations and can be",
        "    unstable.",
    ]

    return "\n".join(lines)
