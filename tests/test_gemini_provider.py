import json
from pathlib import Path

import pytest
from google.genai import types

from src.ai import gemini_provider
from src.ai.gemini_provider import (
    API_KEY_ENV_VAR,
    DEFAULT_MODEL,
    MODEL_ENV_VAR,
    GeminiProvider,
    resolve_model,
    to_gemini_tools,
)
from src.ai.provider import ProviderResponse, ToolCall
from src.ai.tools import TOOL_REGISTRY, tool_schemas

AI_SOURCE_DIR = Path(gemini_provider.__file__).parent


class FakeModelsEndpoint:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)

        if not self._responses:
            raise AssertionError("FakeModelsEndpoint ran out of responses")

        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.models = FakeModelsEndpoint(responses)


def function_call_response(name, args, call_id=None):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                id=call_id, name=name, args=args
                            )
                        )
                    ],
                )
            )
        ]
    )


def text_response(text):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text=text)])
            )
        ]
    )


def test_api_key_is_never_embedded_in_source():
    for source_file in sorted(AI_SOURCE_DIR.glob("*.py")):
        source = source_file.read_text()

        assert "AIza" not in source
        assert "api_key=" not in source

    provider_source = Path(gemini_provider.__file__).read_text()
    assert f'"{API_KEY_ENV_VAR}"' in provider_source
    assert "os.environ" in provider_source


def test_default_model_is_gemini_flash(monkeypatch):
    monkeypatch.delenv(MODEL_ENV_VAR, raising=False)

    assert DEFAULT_MODEL == "gemini-3.7-flash"
    assert resolve_model() == "gemini-3.7-flash"
    assert GeminiProvider(client=FakeClient([])).model == "gemini-3.7-flash"


def test_model_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv(MODEL_ENV_VAR, "gemini-3.7-pro")

    assert resolve_model() == "gemini-3.7-pro"
    assert GeminiProvider(client=FakeClient([])).model == "gemini-3.7-pro"


def test_explicit_model_overrides_environment(monkeypatch):
    monkeypatch.setenv(MODEL_ENV_VAR, "gemini-3.7-pro")

    provider = GeminiProvider(client=FakeClient([]), model="gemini-3.7-flash")

    assert provider.model == "gemini-3.7-flash"


def test_missing_api_key_raises_when_no_client_injected(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    provider = GeminiProvider()

    with pytest.raises(RuntimeError, match=API_KEY_ENV_VAR):
        provider.client


def test_risklab_tool_schemas_convert_to_function_declarations():
    tools = to_gemini_tools(tool_schemas())

    assert len(tools) == 1

    declarations = tools[0].function_declarations
    assert len(declarations) == len(TOOL_REGISTRY)

    by_name = {declaration.name: declaration for declaration in declarations}
    assert set(by_name) == set(TOOL_REGISTRY)

    for name, declaration in by_name.items():
        assert declaration.description == TOOL_REGISTRY[name]["description"]
        assert declaration.parameters_json_schema == TOOL_REGISTRY[name]["parameters"]

    breaches = by_name["get_var_breach_details"]
    assert breaches.parameters_json_schema["properties"]["limit"]["type"] == "integer"
    assert breaches.parameters_json_schema["required"] == ["limit"]


def test_function_calls_convert_to_provider_neutral_tool_calls():
    client = FakeClient(
        [function_call_response("get_var_breach_details", {"limit": 5}, "call_abc")]
    )
    provider = GeminiProvider(client=client, model="gemini-3.7-flash")

    response = provider.respond(
        messages=[{"role": "user", "content": "Inspect the worst breaches."}],
        tools=tool_schemas(),
    )

    assert type(response) is ProviderResponse
    assert response.text is None
    assert len(response.tool_calls) == 1

    call = response.tool_calls[0]
    assert type(call) is ToolCall
    assert call.name == "get_var_breach_details"


def test_function_call_arguments_are_preserved():
    client = FakeClient(
        [function_call_response("get_period_risk_snapshot", {
            "start_date": "2020-03-01",
            "end_date": "2020-03-31",
        })]
    )
    provider = GeminiProvider(client=client)

    response = provider.respond(messages=[{"role": "user", "content": "q"}], tools=[])

    call = response.tool_calls[0]
    assert type(call.arguments) is dict
    assert call.arguments == {"start_date": "2020-03-01", "end_date": "2020-03-31"}


def test_tool_call_ids_are_preserved():
    client = FakeClient(
        [function_call_response("get_model_validation_results", {}, "call_xyz")]
    )
    provider = GeminiProvider(client=client)

    response = provider.respond(messages=[{"role": "user", "content": "q"}], tools=[])

    assert response.tool_calls[0].call_id == "call_xyz"


def test_missing_tool_call_id_is_synthesized():
    client = FakeClient([function_call_response("get_model_validation_results", {})])
    provider = GeminiProvider(client=client)

    response = provider.respond(messages=[{"role": "user", "content": "q"}], tools=[])

    call_id = response.tool_calls[0].call_id
    assert isinstance(call_id, str) and call_id


def test_final_text_converts_to_provider_response():
    client = FakeClient([text_response("Coverage was rejected at the 5% level.")])
    provider = GeminiProvider(client=client)

    response = provider.respond(messages=[{"role": "user", "content": "q"}], tools=[])

    assert type(response) is ProviderResponse
    assert response.text == "Coverage was rejected at the 5% level."
    assert response.tool_calls == []
    assert type(response.continuation_id) is str


def test_system_messages_become_system_instruction():
    client = FakeClient([text_response("ok")])
    provider = GeminiProvider(client=client, model="gemini-3.7-flash")

    provider.respond(
        messages=[
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "question"},
        ],
        tools=tool_schemas(),
    )

    sent = client.models.calls[0]
    assert sent["model"] == "gemini-3.7-flash"
    assert sent["config"].system_instruction == "instructions"
    assert len(sent["contents"]) == 1
    assert sent["contents"][0].role == "user"
    assert sent["contents"][0].parts[0].text == "question"


def test_function_calling_uses_automatic_mode_without_sdk_execution():
    client = FakeClient([text_response("ok")])
    provider = GeminiProvider(client=client)

    provider.respond(messages=[{"role": "user", "content": "q"}], tools=tool_schemas())

    config = client.models.calls[0]["config"]
    mode = config.tool_config.function_calling_config.mode
    assert mode == types.FunctionCallingConfigMode.AUTO
    # The RiskLab agent loop owns tool execution, not the SDK.
    assert config.automatic_function_calling.disable is True


def test_gemini_sdk_objects_do_not_escape_the_provider():
    raw = text_response("final")
    client = FakeClient([raw])
    provider = GeminiProvider(client=client)

    response = provider.respond(messages=[{"role": "user", "content": "q"}], tools=[])

    assert type(response) is ProviderResponse
    assert type(response.text) is str
    for value in (response.text, response.continuation_id, response.tool_calls):
        assert value is not raw
        assert not isinstance(value, types.GenerateContentResponse)
        assert not isinstance(value, types.Content)
        assert not isinstance(value, types.Part)


def test_sequential_tool_results_are_returned_to_gemini():
    client = FakeClient(
        [
            function_call_response("get_model_validation_results", {}, "call_1"),
            function_call_response("get_var_breach_details", {"limit": 3}, "call_2"),
            text_response("Final assessment."),
        ]
    )
    provider = GeminiProvider(client=client)

    first = provider.respond(
        messages=[
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "Assess the model."},
        ],
        tools=tool_schemas(),
    )

    second = provider.respond(
        messages=[],
        tools=tool_schemas(),
        continuation_id=first.continuation_id,
        tool_outputs=[
            {
                "call_id": "call_1",
                "name": "get_model_validation_results",
                "output": json.dumps({"breaches": 118}),
            }
        ],
    )

    assert second.tool_calls[0].name == "get_var_breach_details"

    third = provider.respond(
        messages=[],
        tools=tool_schemas(),
        continuation_id=second.continuation_id,
        tool_outputs=[
            {
                "call_id": "call_2",
                "name": "get_var_breach_details",
                "output": json.dumps({"total_breaches": 118}),
            }
        ],
    )

    assert third.text == "Final assessment."
    assert third.tool_calls == []

    # Turn 2 must replay the question, the model's call, and the tool result.
    second_contents = client.models.calls[1]["contents"]
    assert [content.role for content in second_contents] == ["user", "model", "user"]
    assert second_contents[1].parts[0].function_call.name == (
        "get_model_validation_results"
    )
    function_response = second_contents[2].parts[0].function_response
    assert function_response.name == "get_model_validation_results"
    assert function_response.id == "call_1"
    assert function_response.response == {"breaches": 118}

    # Turn 3 must carry the full accumulated transcript.
    third_contents = client.models.calls[2]["contents"]
    assert [content.role for content in third_contents] == [
        "user",
        "model",
        "user",
        "model",
        "user",
    ]
    assert third_contents[4].parts[0].function_response.name == (
        "get_var_breach_details"
    )


def test_synthesized_call_ids_are_not_echoed_back_to_gemini():
    client = FakeClient(
        [
            function_call_response("get_model_validation_results", {}),
            text_response("done"),
        ]
    )
    provider = GeminiProvider(client=client)

    first = provider.respond(
        messages=[{"role": "user", "content": "q"}], tools=tool_schemas()
    )
    synthesized_id = first.tool_calls[0].call_id

    provider.respond(
        messages=[],
        tools=tool_schemas(),
        continuation_id=first.continuation_id,
        tool_outputs=[
            {
                "call_id": synthesized_id,
                "name": "get_model_validation_results",
                "output": json.dumps({"breaches": 118}),
            }
        ],
    )

    function_response = client.models.calls[1]["contents"][-1].parts[0].function_response
    assert function_response.id is None
    assert function_response.name == "get_model_validation_results"


def test_new_question_resets_conversation_history():
    client = FakeClient([text_response("first"), text_response("second")])
    provider = GeminiProvider(client=client)

    provider.respond(messages=[{"role": "user", "content": "first question"}], tools=[])
    provider.respond(messages=[{"role": "user", "content": "second question"}], tools=[])

    second_contents = client.models.calls[1]["contents"]
    assert len(second_contents) == 1
    assert second_contents[0].parts[0].text == "second question"


def test_provider_conforms_to_llm_provider_protocol():
    provider = GeminiProvider(client=FakeClient([]))

    assert hasattr(provider, "respond")
    assert hasattr(provider, "model")
