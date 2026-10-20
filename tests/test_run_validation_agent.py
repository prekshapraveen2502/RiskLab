import json

import pytest

import run_validation_agent as entry_point
from src.ai.gemini_provider import API_KEY_ENV_VAR as GEMINI_API_KEY_ENV_VAR
from src.ai.gemini_provider import GeminiProvider
from src.ai.openai_provider import API_KEY_ENV_VAR as OPENAI_API_KEY_ENV_VAR
from src.ai.openai_provider import OpenAIProvider

FAKE_GEMINI_KEY = "AIza-test-not-a-real-key-0123456789"
FAKE_OPENAI_KEY = "sk-test-not-a-real-key-0123456789"

VALIDATION_EVIDENCE = {
    "evaluated_forecasts": 1934,
    "breaches": 118,
    "observed_breach_rate": 0.061013443640124095,
    "expected_breach_rate": 0.05,
    "kupiec_lr_statistic": 4.508912345678901,
    "kupiec_p_value": 0.033712345678901,
    "significance_level": 0.05,
    "reject_null": True,
}

BREACH_EVIDENCE = {
    "total_breaches": 118,
    "returned": 2,
    "limit": 5,
    "breaches": [
        {
            "date": "2020-03-16",
            "portfolio_return": -0.0891234567,
            "var_forecast": 0.0212345678,
            "loss_threshold": -0.0212345678,
            "breach_magnitude": 0.0678888889,
        },
        {
            "date": "2020-03-12",
            "portfolio_return": -0.0712345678,
            "var_forecast": 0.0198765432,
            "loss_threshold": -0.0198765432,
            "breach_magnitude": 0.0513580246,
        },
    ],
}

ANSWER = "Observed result: coverage was rejected. Limitations: clustering untested."


class StubProvider:
    def __init__(self, model="gemini-3.7-flash"):
        self.model = model

    def respond(self, messages, tools, continuation_id=None, tool_outputs=None):
        raise AssertionError("StubProvider.respond should not be called")


def fake_result():
    return {
        "answer": ANSWER,
        "tool_calls": [
            {"step": 1, "tool": "get_model_validation_results", "arguments": {}},
            {"step": 2, "tool": "get_var_breach_details", "arguments": {"limit": 5}},
        ],
        "evidence": [
            {"tool": "get_model_validation_results", "result": VALIDATION_EVIDENCE},
            {"tool": "get_var_breach_details", "result": BREACH_EVIDENCE},
        ],
        "steps": 3,
    }


@pytest.fixture
def stub_agent(monkeypatch):
    def run(question, provider, max_steps=6):
        run.calls.append({"question": question, "provider": provider})
        return fake_result()

    run.calls = []
    monkeypatch.setattr(entry_point, "run_validation_agent", run)
    return run


@pytest.fixture
def with_api_key(monkeypatch):
    monkeypatch.delenv(entry_point.PROVIDER_ENV_VAR, raising=False)
    monkeypatch.setenv(GEMINI_API_KEY_ENV_VAR, FAKE_GEMINI_KEY)


def test_entry_point_formats_successful_result(capsys, tmp_path, with_api_key, stub_agent):
    exit_code = entry_point.main([], provider=StubProvider(), report_dir=tmp_path)

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "=== RiskLab AI Validation Agent ===" in output
    assert "Agent Assessment:" in output
    assert ANSWER in output
    assert "Evidence Inspected:" in output
    assert "Tool Calls:" in output
    assert "1. get_model_validation_results()" in output
    assert "2. get_var_breach_details(limit=5)" in output
    assert stub_agent.calls[0]["question"] == entry_point.DEFAULT_QUESTION


def test_provider_and_model_are_displayed(capsys, tmp_path, with_api_key, stub_agent):
    entry_point.main(
        [], provider=StubProvider(model="gemini-3.7-flash"), report_dir=tmp_path
    )

    output = capsys.readouterr().out

    assert "Provider: Gemini" in output
    assert "Model: gemini-3.7-flash" in output


def test_openai_provider_label_is_displayed(
    capsys, tmp_path, monkeypatch, stub_agent
):
    monkeypatch.setenv(entry_point.PROVIDER_ENV_VAR, "openai")
    monkeypatch.setenv(OPENAI_API_KEY_ENV_VAR, FAKE_OPENAI_KEY)

    entry_point.main(
        [], provider=StubProvider(model="gpt-5.6-luna"), report_dir=tmp_path
    )

    output = capsys.readouterr().out

    assert "Provider: OpenAI" in output
    assert "Model: gpt-5.6-luna" in output


def test_selected_tool_names_are_displayed(capsys, tmp_path, with_api_key, stub_agent):
    entry_point.main([], provider=StubProvider(), report_dir=tmp_path)

    output = capsys.readouterr().out

    assert "- get_model_validation_results" in output
    assert "- get_var_breach_details" in output


def test_agent_step_count_is_displayed(capsys, tmp_path, with_api_key, stub_agent):
    entry_point.main([], provider=StubProvider(), report_dir=tmp_path)

    output = capsys.readouterr().out

    assert "Agent Steps:" in output
    assert "\nAgent Steps:\n3" in output


def test_verbose_mode_includes_structured_evidence(
    capsys, tmp_path, with_api_key, stub_agent
):
    entry_point.main(["--verbose"], provider=StubProvider(), report_dir=tmp_path)

    output = capsys.readouterr().out

    assert "Evidence Detail:" in output
    assert "kupiec_p_value" in output
    assert "breach_magnitude" in output
    assert "2020-03-16" in output


def test_default_mode_does_not_dump_large_evidence(
    capsys, tmp_path, with_api_key, stub_agent
):
    entry_point.main([], provider=StubProvider(), report_dir=tmp_path)

    output = capsys.readouterr().out

    assert "Evidence Detail:" not in output
    assert "kupiec_p_value" not in output
    assert "breach_magnitude" not in output
    assert "2020-03-16" not in output


def test_default_provider_is_gemini(monkeypatch, tmp_path, stub_agent):
    monkeypatch.delenv(entry_point.PROVIDER_ENV_VAR, raising=False)
    monkeypatch.setenv(GEMINI_API_KEY_ENV_VAR, FAKE_GEMINI_KEY)

    assert entry_point.DEFAULT_PROVIDER == "gemini"
    assert entry_point.resolve_provider_name() == "gemini"

    entry_point.main([], report_dir=tmp_path)

    assert type(stub_agent.calls[0]["provider"]) is GeminiProvider


def test_gemini_provider_is_selected_by_environment(
    monkeypatch, tmp_path, stub_agent
):
    monkeypatch.setenv(entry_point.PROVIDER_ENV_VAR, "gemini")
    monkeypatch.setenv(GEMINI_API_KEY_ENV_VAR, FAKE_GEMINI_KEY)

    exit_code = entry_point.main([], report_dir=tmp_path)

    assert exit_code == 0
    assert type(stub_agent.calls[0]["provider"]) is GeminiProvider


def test_openai_provider_is_selected_by_environment(
    monkeypatch, tmp_path, stub_agent
):
    monkeypatch.setenv(entry_point.PROVIDER_ENV_VAR, "openai")
    monkeypatch.setenv(OPENAI_API_KEY_ENV_VAR, FAKE_OPENAI_KEY)

    exit_code = entry_point.main([], report_dir=tmp_path)

    assert exit_code == 0
    assert type(stub_agent.calls[0]["provider"]) is OpenAIProvider


def test_provider_name_is_case_insensitive(monkeypatch, tmp_path, stub_agent):
    monkeypatch.setenv(entry_point.PROVIDER_ENV_VAR, "  GEMINI ")
    monkeypatch.setenv(GEMINI_API_KEY_ENV_VAR, FAKE_GEMINI_KEY)

    assert entry_point.resolve_provider_name() == "gemini"

    assert entry_point.main([], report_dir=tmp_path) == 0


def test_unsupported_provider_fails_with_clear_error(
    capsys, monkeypatch, tmp_path, stub_agent
):
    monkeypatch.setenv(entry_point.PROVIDER_ENV_VAR, "mistral")

    exit_code = entry_point.main([], report_dir=tmp_path)

    captured = capsys.readouterr()

    assert exit_code == 2
    assert entry_point.PROVIDER_ENV_VAR in captured.err
    assert "mistral" in captured.err
    assert "'gemini'" in captured.err and "'openai'" in captured.err
    assert stub_agent.calls == []
    assert list(tmp_path.iterdir()) == []


def test_unsupported_provider_raises_typed_error(monkeypatch):
    monkeypatch.setenv(entry_point.PROVIDER_ENV_VAR, "mistral")

    with pytest.raises(entry_point.UnsupportedProviderError, match="Unsupported"):
        entry_point.resolve_provider_name()


def test_missing_gemini_api_key_fails_with_clear_message(
    capsys, tmp_path, monkeypatch, stub_agent
):
    monkeypatch.delenv(entry_point.PROVIDER_ENV_VAR, raising=False)
    monkeypatch.delenv(GEMINI_API_KEY_ENV_VAR, raising=False)

    exit_code = entry_point.main([], provider=StubProvider(), report_dir=tmp_path)

    captured = capsys.readouterr()

    assert exit_code == 2
    assert GEMINI_API_KEY_ENV_VAR in captured.err
    assert "is not set" in captured.err
    assert stub_agent.calls == []
    assert not (tmp_path / entry_point.JSON_REPORT_NAME).exists()


def test_missing_openai_api_key_fails_with_clear_message(
    capsys, tmp_path, monkeypatch, stub_agent
):
    monkeypatch.setenv(entry_point.PROVIDER_ENV_VAR, "openai")
    monkeypatch.delenv(OPENAI_API_KEY_ENV_VAR, raising=False)

    exit_code = entry_point.main([], provider=StubProvider(), report_dir=tmp_path)

    captured = capsys.readouterr()

    assert exit_code == 2
    assert OPENAI_API_KEY_ENV_VAR in captured.err
    assert stub_agent.calls == []


def test_api_key_values_are_never_printed(
    capsys, tmp_path, monkeypatch, stub_agent
):
    monkeypatch.delenv(entry_point.PROVIDER_ENV_VAR, raising=False)
    monkeypatch.setenv(GEMINI_API_KEY_ENV_VAR, FAKE_GEMINI_KEY)
    monkeypatch.setenv(OPENAI_API_KEY_ENV_VAR, FAKE_OPENAI_KEY)

    entry_point.main(["--verbose"], provider=StubProvider(), report_dir=tmp_path)

    captured = capsys.readouterr()
    report = (tmp_path / entry_point.JSON_REPORT_NAME).read_text()
    markdown = (tmp_path / entry_point.MARKDOWN_REPORT_NAME).read_text()

    for text in (captured.out, captured.err, report, markdown):
        assert FAKE_GEMINI_KEY not in text
        assert FAKE_OPENAI_KEY not in text
        assert GEMINI_API_KEY_ENV_VAR not in text
        assert OPENAI_API_KEY_ENV_VAR not in text


def test_successful_run_persists_json_and_markdown(
    capsys, tmp_path, with_api_key, stub_agent
):
    entry_point.main([], provider=StubProvider(), report_dir=tmp_path)

    json_path = tmp_path / entry_point.JSON_REPORT_NAME
    markdown_path = tmp_path / entry_point.MARKDOWN_REPORT_NAME

    assert json_path.exists()
    assert markdown_path.exists()

    report = json.loads(json_path.read_text())
    assert report["provider"] == "gemini"
    assert report["model"] == "gemini-3.7-flash"
    assert report["question"] == entry_point.DEFAULT_QUESTION
    assert report["answer"] == ANSWER
    assert report["evidence_tools"] == [
        "get_model_validation_results",
        "get_var_breach_details",
    ]
    assert report["steps"] == 3
    assert [entry["tool"] for entry in report["tool_calls"]] == [
        "get_model_validation_results",
        "get_var_breach_details",
    ]
    # The artifact proves which tools ran without duplicating their payloads.
    assert "kupiec_p_value" not in json_path.read_text()
    assert "breach_magnitude" not in json_path.read_text()

    markdown = markdown_path.read_text()
    assert markdown.startswith("# RiskLab AI Validation Assessment")
    for heading in (
        "## Provider",
        "## Question",
        "## Agent Assessment",
        "## Evidence Inspected",
        "## Execution Summary",
    ):
        assert heading in markdown
    assert ANSWER in markdown
    assert "Gemini" in markdown


def test_failed_agent_execution_does_not_create_reports(
    capsys, tmp_path, monkeypatch, with_api_key
):
    def failing_run(question, provider, max_steps=6):
        raise RuntimeError("upstream API failure")

    monkeypatch.setattr(entry_point, "run_validation_agent", failing_run)

    exit_code = entry_point.main([], provider=StubProvider(), report_dir=tmp_path)

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "did not complete" in captured.err
    assert "upstream API failure" in captured.err
    assert not (tmp_path / entry_point.JSON_REPORT_NAME).exists()
    assert not (tmp_path / entry_point.MARKDOWN_REPORT_NAME).exists()
    assert list(tmp_path.iterdir()) == []
