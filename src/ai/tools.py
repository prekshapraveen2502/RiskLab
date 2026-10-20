import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
PROCESSED_DIR = DATA_DIR / "processed"

RISK_SUMMARY_PATH = PROCESSED_DIR / "risk_summary.json"
PORTFOLIO_RETURNS_PATH = PROCESSED_DIR / "portfolio_returns.parquet"
ROLLING_VAR_PATH = PROCESSED_DIR / "rolling_historical_var.parquet"
BREACHES_PATH = PROCESSED_DIR / "var_breaches.parquet"

MAX_LIMIT = 100


def _require_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"Required RiskLab output is missing: {path}. "
            "Run run_pipeline.py to regenerate persisted analysis outputs."
        )


def _load_risk_summary() -> dict:
    _require_file(RISK_SUMMARY_PATH)
    return json.loads(RISK_SUMMARY_PATH.read_text())


def _load_series(path: Path, column: str) -> pd.Series:
    _require_file(path)
    return pd.read_parquet(path)[column]


def _validate_limit(limit) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError(f"limit must be an integer, got {type(limit).__name__}")

    if limit <= 0:
        raise ValueError(f"limit must be a positive integer, got {limit}")

    return min(limit, MAX_LIMIT)


def _as_date(value) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def get_portfolio_risk_overview() -> dict:
    summary = _load_risk_summary()

    return {
        "tickers": list(summary["portfolio"]["tickers"]),
        "weights": {
            ticker: float(weight)
            for ticker, weight in summary["portfolio"]["weights"].items()
        },
        "analysis_start_date": str(summary["analysis_period"]["start_date"]),
        "analysis_end_date": str(summary["analysis_period"]["end_date"]),
        "return_observations": int(summary["analysis_period"]["return_observations"]),
        "historical_var_95": float(summary["risk_metrics"]["historical_var_95"]),
        "expected_shortfall_95": float(summary["risk_metrics"]["expected_shortfall_95"]),
    }


def get_model_validation_results() -> dict:
    summary = _load_risk_summary()
    backtest = summary["backtest"]
    kupiec = summary["kupiec_test"]

    return {
        "evaluated_forecasts": int(backtest["observations"]),
        "breaches": int(backtest["breaches"]),
        "observed_breach_rate": float(backtest["breach_rate"]),
        "expected_breach_rate": float(backtest["expected_breach_rate"]),
        "kupiec_lr_statistic": float(kupiec["lr_statistic"]),
        "kupiec_p_value": float(kupiec["p_value"]),
        "significance_level": float(kupiec["significance_level"]),
        "reject_null": bool(kupiec["reject_null"]),
    }


def get_var_breach_details(limit: int = 10) -> dict:
    limit = _validate_limit(limit)

    portfolio_returns = _load_series(PORTFOLIO_RETURNS_PATH, "portfolio_return")
    rolling_var = _load_series(ROLLING_VAR_PATH, "historical_var")
    breaches = _load_series(BREACHES_PATH, "var_breach")

    # Only observations the deterministic engine flagged as True are breaches.
    breach_dates = breaches[breaches.fillna(False).astype(bool)].index

    frame = pd.DataFrame(
        {
            "portfolio_return": portfolio_returns.loc[breach_dates],
            "var_forecast": rolling_var.loc[breach_dates],
        }
    )
    frame["breach_magnitude"] = -frame["portfolio_return"] - frame["var_forecast"]
    frame = frame.sort_values("breach_magnitude", ascending=False)

    rows = [
        {
            "date": _as_date(date),
            "portfolio_return": float(row["portfolio_return"]),
            "var_forecast": float(row["var_forecast"]),
            "loss_threshold": float(-row["var_forecast"]),
            "breach_magnitude": float(row["breach_magnitude"]),
        }
        for date, row in frame.head(limit).iterrows()
    ]

    return {
        "total_breaches": int(len(frame)),
        "returned": int(len(rows)),
        "limit": int(limit),
        "breaches": rows,
    }


def get_worst_portfolio_days(limit: int = 10) -> dict:
    limit = _validate_limit(limit)

    portfolio_returns = _load_series(PORTFOLIO_RETURNS_PATH, "portfolio_return")
    worst = portfolio_returns.sort_values(ascending=True).head(limit)

    return {
        "returned": int(len(worst)),
        "limit": int(limit),
        "worst_days": [
            {"date": _as_date(date), "portfolio_return": float(value)}
            for date, value in worst.items()
        ],
    }


def get_period_risk_snapshot(start_date: str, end_date: str) -> dict:
    for label, value in (("start_date", start_date), ("end_date", end_date)):
        if not isinstance(value, str):
            raise ValueError(f"{label} must be a string, got {type(value).__name__}")

    try:
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
    except ValueError as error:
        raise ValueError(
            f"Invalid date range {start_date} to {end_date}: {error}"
        ) from error

    if start > end:
        raise ValueError(
            f"start_date {start_date} must not be after end_date {end_date}"
        )

    portfolio_returns = _load_series(PORTFOLIO_RETURNS_PATH, "portfolio_return")
    rolling_var = _load_series(ROLLING_VAR_PATH, "historical_var")
    breaches = _load_series(BREACHES_PATH, "var_breach")

    window = portfolio_returns.loc[start:end]

    rows = []
    for date, portfolio_return in window.items():
        var_forecast = rolling_var.loc[date]
        breach = breaches.loc[date]
        rows.append(
            {
                "date": _as_date(date),
                "portfolio_return": float(portfolio_return),
                "rolling_var": None if pd.isna(var_forecast) else float(var_forecast),
                "var_breach": None if pd.isna(breach) else bool(breach),
            }
        )

    return {
        "start_date": _as_date(start),
        "end_date": _as_date(end),
        "observations": int(len(rows)),
        "rows": rows,
    }


TOOL_REGISTRY = {
    "get_portfolio_risk_overview": {
        "description": (
            "Return the portfolio composition and full-sample risk metrics "
            "(tickers, weights, analysis window, return observations, 95% Historical "
            "VaR, 95% Expected Shortfall). Use this first to establish what portfolio "
            "and period the analysis covers."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "function": get_portfolio_risk_overview,
    },
    "get_model_validation_results": {
        "description": (
            "Return the VaR backtest and Kupiec unconditional coverage results "
            "(evaluated forecasts, breaches, observed and expected breach rates, "
            "Kupiec LR statistic, p-value, significance level, reject_null). Use this "
            "whenever the question concerns model validity, coverage, or whether the "
            "breach frequency is statistically acceptable."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "function": get_model_validation_results,
    },
    "get_var_breach_details": {
        "description": (
            "Return the individual dates where the portfolio loss exceeded the VaR "
            "forecast, sorted from most to least severe by breach magnitude "
            "((-portfolio_return) - var_forecast). Use this to assess breach severity "
            "or identify when the model failed, rather than only how often."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_LIMIT,
                    "description": "Maximum number of breaches to return (1-100).",
                }
            },
            "required": ["limit"],
            "additionalProperties": False,
        },
        "function": get_var_breach_details,
    },
    "get_worst_portfolio_days": {
        "description": (
            "Return the worst portfolio return days, ordered from worst to least "
            "severe. Use this to judge tail severity, including losses that did not "
            "breach the VaR forecast."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_LIMIT,
                    "description": "Maximum number of days to return (1-100).",
                }
            },
            "required": ["limit"],
            "additionalProperties": False,
        },
        "function": get_worst_portfolio_days,
    },
    "get_period_risk_snapshot": {
        "description": (
            "Return per-date portfolio return, rolling VaR forecast, and breach flag "
            "for an inclusive date range (YYYY-MM-DD). Use this to examine a specific "
            "stress window or to check whether breaches cluster in time."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Inclusive start date, YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "Inclusive end date, YYYY-MM-DD.",
                },
            },
            "required": ["start_date", "end_date"],
            "additionalProperties": False,
        },
        "function": get_period_risk_snapshot,
    },
}


def tool_schemas() -> list[dict]:
    return [
        {
            "name": name,
            "description": entry["description"],
            "parameters": entry["parameters"],
        }
        for name, entry in TOOL_REGISTRY.items()
    ]


def execute_tool(name: str, arguments: dict | None = None) -> dict:
    if name not in TOOL_REGISTRY:
        raise ValueError(
            f"Unknown tool: {name}. Registered tools: {sorted(TOOL_REGISTRY)}"
        )

    arguments = {} if arguments is None else arguments

    if not isinstance(arguments, dict):
        raise ValueError(
            f"Tool arguments for {name} must be an object, "
            f"got {type(arguments).__name__}"
        )

    allowed = set(TOOL_REGISTRY[name]["parameters"]["properties"])
    unexpected = sorted(set(arguments) - allowed)
    if unexpected:
        raise ValueError(
            f"Tool {name} received unexpected arguments: {unexpected}. "
            f"Allowed: {sorted(allowed)}"
        )

    return TOOL_REGISTRY[name]["function"](**arguments)
