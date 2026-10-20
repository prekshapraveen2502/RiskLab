import pytest

from src.ai import tools
from src.ai.provider import ProviderResponse, ToolCall
from src.ai.tools import (
    get_model_validation_results,
    get_var_breach_details,
    tool_schemas,
)
from src.ai.validation_agent import (
    SYSTEM_PROMPT,
    MaxStepsExceededError,
    build_messages,
    run_validation_agent,
)

PARQUET_PATHS = (
    tools.PORTFOLIO_RETURNS_PATH,
    tools.ROLLING_VAR_PATH,
    tools.BREACHES_PATH,
)

requires_outputs = pytest.mark.skipif(
    not all(
        path.exists() for path in (*PARQUET_PATHS, tools.RISK_SUMMARY_PATH)
    ),
    reason="Persisted outputs are gitignored; run run_pipeline.py to generate them",
)


class ScriptedProvider:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def respond(self, messages, tools, continuation_id=None, tool_outputs=None):
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "continuation_id": continuation_id,
                "tool_outputs": tool_outputs,
            }
        )

        if not self._responses:
            raise AssertionError("ScriptedProvider ran out of scripted responses")

        return self._responses.pop(0)


class LoopingProvider:
    def __init__(self):
        self.call_count = 0

    def respond(self, messages, tools, continuation_id=None, tool_outputs=None):
        self.call_count += 1
        return ProviderResponse(
            tool_calls=[
                ToolCall(
                    name="get_model_validation_results",
                    arguments={},
                    call_id=f"call_{self.call_count}",
                )
            ],
            continuation_id=f"resp_{self.call_count}",
        )


def snapshot_files():
    return {
        str(path): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in (*PARQUET_PATHS, tools.RISK_SUMMARY_PATH)
        if path.exists()
    }


@requires_outputs
def test_single_tool_call_then_final_answer():
    provider = ScriptedProvider(
        [
            ProviderResponse(
                tool_calls=[
                    ToolCall("get_model_validation_results", {}, call_id="call_1")
                ],
                continuation_id="resp_1",
            ),
            ProviderResponse(text="Coverage was not rejected.", continuation_id="resp_2"),
        ]
    )

    result = run_validation_agent("Is coverage acceptable?", provider)

    assert result["answer"] == "Coverage was not rejected."
    assert result["steps"] == 2
    assert result["tool_calls"] == [
        {"step": 1, "tool": "get_model_validation_results", "arguments": {}}
    ]
    assert result["evidence"] == [
        {"tool": "get_model_validation_results", "result": get_model_validation_results()}
    ]


@requires_outputs
def test_multiple_sequential_tool_calls_then_final_answer():
    provider = ScriptedProvider(
        [
            ProviderResponse(
                tool_calls=[
                    ToolCall("get_model_validation_results", {}, call_id="call_1")
                ],
                continuation_id="resp_1",
            ),
            ProviderResponse(
                tool_calls=[
                    ToolCall("get_var_breach_details", {"limit": 5}, call_id="call_2")
                ],
                continuation_id="resp_2",
            ),
            ProviderResponse(text="Final assessment.", continuation_id="resp_3"),
        ]
    )

    result = run_validation_agent("Assess coverage and breach severity.", provider)

    assert result["answer"] == "Final assessment."
    assert result["steps"] == 3

    assert [entry["tool"] for entry in result["tool_calls"]] == [
        "get_model_validation_results",
        "get_var_breach_details",
    ]
    assert [entry["step"] for entry in result["tool_calls"]] == [1, 2]
    assert result["tool_calls"][1]["arguments"] == {"limit": 5}

    assert [entry["tool"] for entry in result["evidence"]] == [
        "get_model_validation_results",
        "get_var_breach_details",
    ]
    assert result["evidence"][0]["result"] == get_model_validation_results()
    assert result["evidence"][1]["result"] == get_var_breach_details(limit=5)

    # Tool results must be handed back to the provider keyed to their call_id.
    second_turn = provider.calls[1]
    assert second_turn["continuation_id"] == "resp_1"
    assert second_turn["tool_outputs"][0]["call_id"] == "call_1"
    assert provider.calls[2]["tool_outputs"][0]["call_id"] == "call_2"


@requires_outputs
def test_exactly_one_final_answer_is_returned():
    provider = ScriptedProvider(
        [
            ProviderResponse(
                tool_calls=[
                    ToolCall("get_portfolio_risk_overview", {}, call_id="call_1")
                ]
            ),
            ProviderResponse(text="The single final answer."),
            ProviderResponse(text="Should never be reached."),
        ]
    )

    result = run_validation_agent("Summarise the portfolio.", provider)

    assert result["answer"] == "The single final answer."
    assert len(provider.calls) == 2
    assert type(result["steps"]) is int


def test_unknown_tool_fails_clearly():
    provider = ScriptedProvider(
        [ProviderResponse(tool_calls=[ToolCall("execute_python", {"code": "1"})])]
    )

    with pytest.raises(ValueError, match="Unknown tool: execute_python"):
        run_validation_agent("Run something dangerous.", provider)


def test_malformed_json_arguments_fail_clearly():
    provider = ScriptedProvider(
        [
            ProviderResponse(
                tool_calls=[ToolCall("get_var_breach_details", "{not valid json")]
            )
        ]
    )

    with pytest.raises(ValueError, match="not valid JSON"):
        run_validation_agent("Inspect breaches.", provider)


def test_non_object_arguments_fail_clearly():
    provider = ScriptedProvider(
        [ProviderResponse(tool_calls=[ToolCall("get_var_breach_details", "[1, 2]")])]
    )

    with pytest.raises(ValueError, match="must decode to an object"):
        run_validation_agent("Inspect breaches.", provider)


@requires_outputs
def test_invalid_tool_arguments_fail_clearly():
    provider = ScriptedProvider(
        [
            ProviderResponse(
                tool_calls=[ToolCall("get_var_breach_details", {"limit": -5})]
            )
        ]
    )

    with pytest.raises(ValueError, match="positive integer"):
        run_validation_agent("Inspect breaches.", provider)


@requires_outputs
def test_unexpected_tool_arguments_fail_clearly():
    provider = ScriptedProvider(
        [
            ProviderResponse(
                tool_calls=[ToolCall("get_var_breach_details", {"sql": "DROP TABLE"})]
            )
        ]
    )

    with pytest.raises(ValueError, match="unexpected arguments"):
        run_validation_agent("Inspect breaches.", provider)


@requires_outputs
def test_max_steps_stops_infinite_provider_loop():
    provider = LoopingProvider()

    with pytest.raises(MaxStepsExceededError, match="stopped after 3 steps"):
        run_validation_agent("Loop forever.", provider, max_steps=3)

    assert provider.call_count == 3


def test_max_steps_must_be_positive():
    provider = ScriptedProvider([ProviderResponse(text="unused")])

    with pytest.raises(ValueError, match="max_steps must be a positive integer"):
        run_validation_agent("Question?", provider, max_steps=0)


def test_question_must_be_non_empty():
    with pytest.raises(ValueError, match="non-empty string"):
        build_messages("   ")


@requires_outputs
def test_agent_run_does_not_modify_persisted_data():
    before = snapshot_files()
    provider = ScriptedProvider(
        [
            ProviderResponse(
                tool_calls=[
                    ToolCall("get_model_validation_results", {}, call_id="call_1")
                ]
            ),
            ProviderResponse(
                tool_calls=[
                    ToolCall("get_var_breach_details", {"limit": 3}, call_id="call_2")
                ]
            ),
            ProviderResponse(text="Done."),
        ]
    )

    run_validation_agent("Assess the model.", provider)

    assert snapshot_files() == before


def test_agent_exposes_only_registered_tool_schemas():
    provider = ScriptedProvider([ProviderResponse(text="No tools needed.")])

    run_validation_agent("Explain your limitations.", provider)

    assert provider.calls[0]["tools"] == tool_schemas()
    assert provider.calls[0]["messages"][0]["role"] == "system"
    assert provider.calls[0]["messages"][0]["content"] == SYSTEM_PROMPT
    assert provider.calls[0]["messages"][1]["role"] == "user"


def test_system_prompt_prohibits_invented_metrics():
    prompt = SYSTEM_PROMPT.lower()

    assert "never invent" in prompt
    assert "do not output any number that was not returned by a tool" in prompt


def test_system_prompt_prohibits_llm_recomputation():
    prompt = SYSTEM_PROMPT.lower()

    assert "never recompute risk statistics yourself" in prompt
    assert "authoritative" in prompt


def test_system_prompt_distinguishes_non_rejection_from_correctness():
    prompt = SYSTEM_PROMPT.lower()

    assert "not evidence that the model is correct" in prompt
    assert "unconditional coverage was not rejected at the selected significance level" in prompt
    assert "never claim the model is proven, correct, validated, or verified" in prompt


def test_system_prompt_requires_deterministic_tools_for_quantitative_evidence():
    prompt = SYSTEM_PROMPT.lower()

    assert "must call the registered tools whenever quantitative evidence is needed" in prompt


def test_system_prompt_states_statistical_limitations():
    prompt = SYSTEM_PROMPT.lower()

    assert "does not test breach independence" in prompt
    assert "clustering" in prompt
    assert "representative" in prompt
    assert "thin tails" in prompt


def test_system_prompt_requires_structured_distinctions():
    prompt = SYSTEM_PROMPT.lower()

    assert "observed result" in prompt
    assert "statistical interpretation" in prompt
    assert "limitations" in prompt
    assert "recommended follow-up" in prompt


def test_system_prompt_discourages_gratuitous_tool_use():
    prompt = SYSTEM_PROMPT.lower()

    assert "do not request irrelevant tools just to appear agentic" in prompt
