import argparse
import json
import os
import sys
from pathlib import Path

from src.ai.gemini_provider import GeminiProvider
from src.ai.gemini_provider import API_KEY_ENV_VAR as GEMINI_API_KEY_ENV_VAR
from src.ai.openai_provider import API_KEY_ENV_VAR as OPENAI_API_KEY_ENV_VAR
from src.ai.openai_provider import OpenAIProvider
from src.ai.validation_agent import run_validation_agent

PROVIDER_ENV_VAR = "RISKLAB_LLM_PROVIDER"
DEFAULT_PROVIDER = "gemini"

PROVIDERS = {
    "gemini": {
        "label": "Gemini",
        "factory": GeminiProvider,
        "api_key_env_var": GEMINI_API_KEY_ENV_VAR,
    },
    "openai": {
        "label": "OpenAI",
        "factory": OpenAIProvider,
        "api_key_env_var": OPENAI_API_KEY_ENV_VAR,
    },
}

DEFAULT_QUESTION = (
    "Assess the current Historical VaR model. Determine whether its "
    "unconditional coverage is statistically acceptable, inspect the most "
    "severe VaR breaches before reaching a conclusion, and identify important "
    "limitations or follow-up validation work."
)

REPORT_DIR = Path(__file__).parent / "data" / "processed"
JSON_REPORT_NAME = "ai_validation_report.json"
MARKDOWN_REPORT_NAME = "ai_validation_report.md"


class MissingCredentialsError(RuntimeError):
    pass


class UnsupportedProviderError(RuntimeError):
    pass


def resolve_provider_name(environ=None) -> str:
    environ = os.environ if environ is None else environ
    name = (environ.get(PROVIDER_ENV_VAR) or DEFAULT_PROVIDER).strip().lower()

    if name not in PROVIDERS:
        raise UnsupportedProviderError(
            f"Unsupported {PROVIDER_ENV_VAR}: {name!r}. "
            f"Supported providers: {sorted(PROVIDERS)}."
        )

    return name


def create_provider(name: str):
    return PROVIDERS[name]["factory"]()


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the RiskLab AI validation agent against the real LLM."
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Also print the structured evidence returned by each tool.",
    )
    return parser.parse_args(argv)


def require_api_key(provider_name: str, environ=None) -> None:
    environ = os.environ if environ is None else environ
    env_var = PROVIDERS[provider_name]["api_key_env_var"]

    if not environ.get(env_var):
        raise MissingCredentialsError(
            f"{env_var} is not set. Export it before running the "
            f"{PROVIDERS[provider_name]['label']} provider, for example: "
            f"export {env_var}=... . RiskLab never stores API credentials in "
            "the repository."
        )


def evidence_tool_names(result: dict) -> list[str]:
    names = []
    for entry in result.get("evidence", []):
        if entry["tool"] not in names:
            names.append(entry["tool"])
    return names


def format_arguments(arguments: dict) -> str:
    return ", ".join(f"{key}={value!r}" for key, value in sorted(arguments.items()))


def format_tool_call(entry: dict) -> str:
    return f"{entry['tool']}({format_arguments(entry['arguments'])})"


def format_result(
    provider_label: str,
    model: str,
    result: dict,
    verbose: bool = False,
) -> str:
    tool_calls = result.get("tool_calls", [])

    lines = [
        "=== RiskLab AI Validation Agent ===",
        "",
        f"Provider: {provider_label}",
        f"Model: {model}",
        "",
        "Agent Assessment:",
        result.get("answer") or "(no answer returned)",
        "",
        "Evidence Inspected:",
    ]

    evidence_names = evidence_tool_names(result)
    lines += [f"- {name}" for name in evidence_names] or ["- (none)"]

    lines += ["", "Tool Calls:"]
    if tool_calls:
        lines += [
            f"{index}. {format_tool_call(entry)}"
            for index, entry in enumerate(tool_calls, start=1)
        ]
    else:
        lines.append("(none)")

    lines += ["", "Agent Steps:", str(result.get("steps"))]

    if verbose:
        lines += ["", "Evidence Detail:"]
        for entry in result.get("evidence", []):
            lines.append(f"--- {entry['tool']} ---")
            lines.append(json.dumps(entry["result"], indent=2, allow_nan=False))

    return "\n".join(lines)


def build_json_report(
    provider_name: str,
    model: str,
    question: str,
    result: dict,
) -> dict:
    return {
        "provider": provider_name,
        "model": model,
        "question": question,
        "answer": result.get("answer"),
        "tool_calls": result.get("tool_calls", []),
        "evidence_tools": evidence_tool_names(result),
        "steps": result.get("steps"),
    }


def build_markdown_report(
    provider_label: str,
    model: str,
    question: str,
    result: dict,
) -> str:
    evidence_names = evidence_tool_names(result)
    tool_calls = result.get("tool_calls", [])

    lines = [
        "# RiskLab AI Validation Assessment",
        "",
        "## Provider",
        "",
        f"{provider_label} (`{model}`)",
        "",
        "## Question",
        "",
        question,
        "",
        "## Agent Assessment",
        "",
        result.get("answer") or "(no answer returned)",
        "",
        "## Evidence Inspected",
        "",
    ]

    lines += [f"- `{name}`" for name in evidence_names] or ["- (none)"]

    lines += [
        "",
        "## Execution Summary",
        "",
        f"- Provider: {provider_label}",
        f"- Model: `{model}`",
        f"- Agent steps: {result.get('steps')}",
        f"- Tool calls: {len(tool_calls)}",
        "",
    ]

    if tool_calls:
        lines += [
            f"{index}. `{format_tool_call(entry)}`"
            for index, entry in enumerate(tool_calls, start=1)
        ]
    else:
        lines.append("No tools were called.")

    return "\n".join(lines) + "\n"


def save_reports(
    provider_name: str,
    model: str,
    question: str,
    result: dict,
    report_dir: Path = REPORT_DIR,
) -> dict:
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    json_path = report_dir / JSON_REPORT_NAME
    markdown_path = report_dir / MARKDOWN_REPORT_NAME
    label = PROVIDERS[provider_name]["label"]

    json_path.write_text(
        json.dumps(
            build_json_report(provider_name, model, question, result),
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )
    markdown_path.write_text(
        build_markdown_report(label, model, question, result)
    )

    return {"json": json_path, "markdown": markdown_path}


def main(
    argv=None,
    provider=None,
    report_dir: Path = REPORT_DIR,
    question: str = DEFAULT_QUESTION,
) -> int:
    args = parse_args(argv)

    try:
        provider_name = resolve_provider_name()
        require_api_key(provider_name)
    except (UnsupportedProviderError, MissingCredentialsError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    label = PROVIDERS[provider_name]["label"]

    if provider is None:
        provider = create_provider(provider_name)

    try:
        result = run_validation_agent(question, provider)
    except Exception as error:
        print(
            f"Error: the validation agent did not complete: "
            f"{type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1

    print(format_result(label, provider.model, result, verbose=args.verbose))

    paths = save_reports(
        provider_name, provider.model, question, result, report_dir=report_dir
    )
    print()
    print("Reports written:")
    for path in paths.values():
        print(f"  {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
