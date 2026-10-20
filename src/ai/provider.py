from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict
    call_id: str | None = None


@dataclass(frozen=True)
class ProviderResponse:
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    continuation_id: str | None = None


class LLMProvider(Protocol):
    def respond(
        self,
        messages: list[dict],
        tools: list[dict],
        continuation_id: str | None = None,
        tool_outputs: list[dict] | None = None,
    ) -> ProviderResponse:
        """Return the next provider turn, either final text or tool calls."""
        ...
