import json
import os

from google.genai import types

from src.ai.provider import ProviderResponse, ToolCall

API_KEY_ENV_VAR = "GEMINI_API_KEY"
MODEL_ENV_VAR = "RISKLAB_LLM_MODEL"
DEFAULT_MODEL = "gemini-3.7-flash"


def resolve_model(model: str | None = None) -> str:
    return model or os.environ.get(MODEL_ENV_VAR) or DEFAULT_MODEL


def to_gemini_tools(schemas: list[dict]) -> list[types.Tool]:
    declarations = [
        types.FunctionDeclaration(
            name=schema["name"],
            description=schema["description"],
            parameters_json_schema=schema["parameters"],
        )
        for schema in schemas
    ]

    return [types.Tool(function_declarations=declarations)] if declarations else []


class GeminiProvider:
    def __init__(self, client=None, model: str | None = None):
        self._client = client
        self.model = resolve_model(model)
        self._system_instruction = None
        self._history = []
        self._turn = 0
        self._issued_call_ids = set()

    @property
    def client(self):
        if self._client is None:
            if not os.environ.get(API_KEY_ENV_VAR):
                raise RuntimeError(
                    f"{API_KEY_ENV_VAR} is not set. Export it in the environment; "
                    "RiskLab never stores API credentials in the repository."
                )

            from google import genai

            # The SDK reads the credential from the environment itself.
            self._client = genai.Client()

        return self._client

    def respond(
        self,
        messages: list[dict],
        tools: list[dict],
        continuation_id: str | None = None,
        tool_outputs: list[dict] | None = None,
    ) -> ProviderResponse:
        if tool_outputs:
            self._history.append(self._to_function_response_content(tool_outputs))
        else:
            self._start_conversation(messages)

        response = self.client.models.generate_content(
            model=self.model,
            contents=list(self._history),
            config=self._build_config(tools),
        )

        model_content = self._model_content(response)
        if model_content is not None:
            self._history.append(model_content)

        return self._to_provider_response(response)

    def _start_conversation(self, messages: list[dict]) -> None:
        self._system_instruction = None
        self._history = []
        self._issued_call_ids = set()

        for message in messages:
            role = message["role"]
            if role == "system":
                self._system_instruction = message["content"]
                continue

            self._history.append(
                types.Content(
                    role="model" if role == "assistant" else "user",
                    parts=[types.Part(text=message["content"])],
                )
            )

    def _build_config(self, tools: list[dict]) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=self._system_instruction,
            tools=to_gemini_tools(tools),
            # AUTO leaves the tool decision entirely to the model.
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.AUTO
                )
            ),
            # The RiskLab agent loop executes tools; the SDK must not.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

    def _to_function_response_content(self, tool_outputs: list[dict]) -> types.Content:
        parts = []

        for output in tool_outputs:
            call_id = output.get("call_id")
            parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        # Only echo identifiers Gemini itself issued.
                        id=call_id if call_id in self._issued_call_ids else None,
                        name=output["name"],
                        response=self._to_response_payload(output["output"]),
                    )
                )
            )

        return types.Content(role="user", parts=parts)

    @staticmethod
    def _to_response_payload(output) -> dict:
        if isinstance(output, dict):
            return output

        parsed = json.loads(output)

        # Gemini requires the function response to be a JSON object.
        return parsed if isinstance(parsed, dict) else {"result": parsed}

    @staticmethod
    def _model_content(response):
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return None

        return getattr(candidates[0], "content", None)

    def _to_provider_response(self, response) -> ProviderResponse:
        tool_calls = []
        text_parts = []

        content = self._model_content(response)
        for part in (getattr(content, "parts", None) or []) if content else []:
            function_call = getattr(part, "function_call", None)
            if function_call is not None:
                tool_calls.append(self._to_tool_call(function_call))
                continue

            text = getattr(part, "text", None)
            if text:
                text_parts.append(text)

        self._turn += 1

        return ProviderResponse(
            text="".join(text_parts) or None,
            tool_calls=tool_calls,
            continuation_id=f"gemini-turn-{self._turn}",
        )

    def _to_tool_call(self, function_call) -> ToolCall:
        name = getattr(function_call, "name", None)
        call_id = getattr(function_call, "id", None)

        if call_id:
            self._issued_call_ids.add(call_id)
        else:
            # Gemini may omit identifiers; the agent loop still needs a handle.
            call_id = f"gemini-call-{len(self._issued_call_ids) + self._turn + 1}"

        return ToolCall(
            name=name,
            arguments=dict(getattr(function_call, "args", None) or {}),
            call_id=call_id,
        )
