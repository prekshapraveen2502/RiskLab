import json
import os

from src.ai.provider import ProviderResponse, ToolCall

API_KEY_ENV_VAR = "OPENAI_API_KEY"
MODEL_ENV_VAR = "RISKLAB_LLM_MODEL"
DEFAULT_MODEL = "gpt-5.6-luna"


def resolve_model(model: str | None = None) -> str:
    return model or os.environ.get(MODEL_ENV_VAR) or DEFAULT_MODEL


def to_openai_tools(schemas: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "name": schema["name"],
            "description": schema["description"],
            "parameters": schema["parameters"],
            "strict": True,
        }
        for schema in schemas
    ]


def _attribute(item, key, default=None):
    # Response items may arrive as SDK objects or plain dicts.
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _parse_arguments(name: str, raw) -> dict:
    if raw is None or raw == "":
        return {}

    if isinstance(raw, dict):
        return raw

    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"OpenAI returned arguments for {name} that are not valid JSON: {error}"
        ) from error

    if not isinstance(parsed, dict):
        raise ValueError(
            f"OpenAI returned arguments for {name} that are not an object: {parsed!r}"
        )

    return parsed


class OpenAIProvider:
    def __init__(self, client=None, model: str | None = None):
        self._client = client
        self.model = resolve_model(model)

    @property
    def client(self):
        if self._client is None:
            if not os.environ.get(API_KEY_ENV_VAR):
                raise RuntimeError(
                    f"{API_KEY_ENV_VAR} is not set. Export it in the environment; "
                    "RiskLab never stores API credentials in the repository."
                )

            from openai import OpenAI

            self._client = OpenAI()

        return self._client

    def respond(
        self,
        messages: list[dict],
        tools: list[dict],
        continuation_id: str | None = None,
        tool_outputs: list[dict] | None = None,
    ) -> ProviderResponse:
        if tool_outputs:
            # Continuation turns carry only the outputs keyed to their call_id.
            input_items = [
                {
                    "type": "function_call_output",
                    "call_id": output["call_id"],
                    "output": output["output"],
                }
                for output in tool_outputs
            ]
        else:
            input_items = [self._to_input_message(message) for message in messages]

        response = self.client.responses.create(
            model=self.model,
            input=input_items,
            tools=to_openai_tools(tools),
            previous_response_id=continuation_id,
        )

        return self._to_provider_response(response)

    @staticmethod
    def _to_input_message(message: dict) -> dict:
        role = message["role"]
        # The Responses API expects developer-role instructions.
        return {
            "role": "developer" if role == "system" else role,
            "content": message["content"],
        }

    @staticmethod
    def _to_provider_response(response) -> ProviderResponse:
        tool_calls = []
        text_parts = []

        for item in _attribute(response, "output", []) or []:
            item_type = _attribute(item, "type")

            if item_type == "function_call":
                name = _attribute(item, "name")
                tool_calls.append(
                    ToolCall(
                        name=name,
                        arguments=_parse_arguments(name, _attribute(item, "arguments")),
                        call_id=_attribute(item, "call_id"),
                    )
                )
            elif item_type == "message":
                for content in _attribute(item, "content", []) or []:
                    if _attribute(content, "type") == "output_text":
                        text_parts.append(_attribute(content, "text") or "")

        text = "".join(text_parts) or _attribute(response, "output_text") or None

        return ProviderResponse(
            text=text,
            tool_calls=tool_calls,
            continuation_id=_attribute(response, "id"),
        )
