import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ai import openai_provider
from src.ai.openai_provider import (
    API_KEY_ENV_VAR,
    DEFAULT_MODEL,
    MODEL_ENV_VAR,
    OpenAIProvider,
    resolve_model,
    to_openai_tools,
)
from src.ai.provider import ProviderResponse, ToolCall
from src.ai.tools import TOOL_REGISTRY, tool_schemas

AI_SOURCE_DIR = Path(openai_provider.__file__).parent


class FakeResponsesEndpoint:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)

        if not self._responses:
            raise AssertionError("FakeResponsesEndpoint ran out of responses")

        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.responses = FakeResponsesEndpoint(responses)


def function_call_response(name, arguments, call_id, response_id="resp_1"):
    return SimpleNamespace(
        id=response_id,
        output=[
            SimpleNamespace(
                type="function_call",
                name=name,
                arguments=arguments,
                call_id=call_id,
            )
        ],
        output_text="",
    )


def text_response(text, response_id="resp_2"):
    return SimpleNamespace(
        id=response_id,
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text=text)],
            )
        ],
        output_text=text,
    )


def test_tool_registry_converts_to_valid_function_tools():
    openai_tools = to_openai_tools(tool_schemas())

    assert len(openai_tools) == len(TOOL_REGISTRY)

    for tool in openai_tools:
        assert tool["type"] == "function"
        assert tool["name"] in TOOL_REGISTRY
        assert tool["strict"] is True
        assert isinstance(tool["description"], str) and tool["description"]

        parameters = tool["parameters"]
        assert parameters["type"] == "object"
        assert parameters["additionalProperties"] is False
        # strict mode requires every declared property to be required.
        assert set(parameters["required"]) == set(parameters["properties"])

        json.dumps(tool)


def test_model_defaults_when_env_var_absent(monkeypatch):
    monkeypatch.delenv(MODEL_ENV_VAR, raising=False)

    assert resolve_model() == DEFAULT_MODEL
    assert OpenAIProvider(client=FakeClient([])).model == DEFAULT_MODEL


def test_model_comes_from_environment_variable(monkeypatch):
    monkeypatch.setenv(MODEL_ENV_VAR, "gpt-4.1-mini")

    assert resolve_model() == "gpt-4.1-mini"
    assert OpenAIProvider(client=FakeClient([])).model == "gpt-4.1-mini"


def test_explicit_model_overrides_environment(monkeypatch):
    monkeypatch.setenv(MODEL_ENV_VAR, "gpt-4.1-mini")

    assert OpenAIProvider(client=FakeClient([]), model="gpt-4.1").model == "gpt-4.1"


def test_api_key_is_not_embedded_in_source():
    for source_file in sorted(AI_SOURCE_DIR.glob("*.py")):
        source = source_file.read_text()

        assert "sk-" not in source
        assert "api_key=" not in source

    provider_source = Path(openai_provider.__file__).read_text()
    assert f'"{API_KEY_ENV_VAR}"' in provider_source
    assert "os.environ" in provider_source


def test_missing_api_key_raises_when_no_client_injected(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    provider = OpenAIProvider()

    with pytest.raises(RuntimeError, match=API_KEY_ENV_VAR):
        provider.client


def test_function_calls_convert_to_provider_neutral_tool_calls():
    client = FakeClient(
        [function_call_response("get_var_breach_details", '{"limit": 5}', "call_abc")]
    )
    provider = OpenAIProvider(client=client, model="gpt-4.1")

    response = provider.respond(
        messages=[{"role": "system", "content": "instructions"}],
        tools=tool_schemas(),
    )

    assert type(response) is ProviderResponse
    assert response.text is None
    assert response.continuation_id == "resp_1"
    assert len(response.tool_calls) == 1

    call = response.tool_calls[0]
    assert type(call) is ToolCall
    assert call.name == "get_var_breach_details"
    assert call.arguments == {"limit": 5}
    assert type(call.arguments) is dict
    assert call.call_id == "call_abc"


def test_final_text_converts_to_provider_response():
    client = FakeClient([text_response("Coverage was not rejected.")])
    provider = OpenAIProvider(client=client, model="gpt-4.1")

    response = provider.respond(messages=[{"role": "user", "content": "q"}], tools=[])

    assert type(response) is ProviderResponse
    assert response.text == "Coverage was not rejected."
    assert response.tool_calls == []
    assert response.continuation_id == "resp_2"


def test_system_messages_are_sent_as_developer_instructions():
    client = FakeClient([text_response("ok")])
    provider = OpenAIProvider(client=client, model="gpt-4.1")

    provider.respond(
        messages=[
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "question"},
        ],
        tools=tool_schemas(),
    )

    sent = client.responses.calls[0]
    assert sent["model"] == "gpt-4.1"
    assert sent["input"][0] == {"role": "developer", "content": "instructions"}
    assert sent["input"][1] == {"role": "user", "content": "question"}
    assert sent["previous_response_id"] is None


def test_tool_outputs_preserve_call_id_and_continuation():
    client = FakeClient([text_response("final")])
    provider = OpenAIProvider(client=client, model="gpt-4.1")

    provider.respond(
        messages=[{"role": "user", "content": "question"}],
        tools=tool_schemas(),
        continuation_id="resp_1",
        tool_outputs=[
            {
                "call_id": "call_abc",
                "name": "get_var_breach_details",
                "output": '{"total_breaches": 3}',
            }
        ],
    )

    sent = client.responses.calls[0]
    assert sent["previous_response_id"] == "resp_1"
    assert sent["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_abc",
            "output": '{"total_breaches": 3}',
        }
    ]


def test_malformed_function_arguments_fail_clearly():
    client = FakeClient(
        [function_call_response("get_var_breach_details", "{not json", "call_abc")]
    )
    provider = OpenAIProvider(client=client, model="gpt-4.1")

    with pytest.raises(ValueError, match="not valid JSON"):
        provider.respond(messages=[{"role": "user", "content": "q"}], tools=[])


def test_dict_shaped_response_items_are_supported():
    client = FakeClient(
        [
            {
                "id": "resp_9",
                "output": [
                    {
                        "type": "function_call",
                        "name": "get_portfolio_risk_overview",
                        "arguments": "{}",
                        "call_id": "call_9",
                    }
                ],
            }
        ]
    )
    provider = OpenAIProvider(client=client, model="gpt-4.1")

    response = provider.respond(messages=[{"role": "user", "content": "q"}], tools=[])

    assert response.tool_calls[0].name == "get_portfolio_risk_overview"
    assert response.tool_calls[0].call_id == "call_9"
    assert response.continuation_id == "resp_9"


def test_openai_objects_do_not_leak_outside_adapter():
    raw = text_response("final")
    client = FakeClient([raw])
    provider = OpenAIProvider(client=client, model="gpt-4.1")

    response = provider.respond(messages=[{"role": "user", "content": "q"}], tools=[])

    assert type(response) is ProviderResponse
    assert type(response.text) is str
    assert type(response.continuation_id) is str
    for value in (response.text, response.continuation_id, response.tool_calls):
        assert value is not raw
        assert not isinstance(value, SimpleNamespace)


def test_agent_modules_do_not_import_openai():
    for module_name in ("tools.py", "validation_agent.py", "reporting.py", "provider.py"):
        source = (AI_SOURCE_DIR / module_name).read_text()

        assert "openai" not in source.lower()
