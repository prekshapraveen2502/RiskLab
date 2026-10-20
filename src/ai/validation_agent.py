import json

from src.ai.provider import LLMProvider
from src.ai.tools import execute_tool, tool_schemas

SYSTEM_PROMPT = """\
You are the RiskLab Risk Validation Agent. You assess the quality and validity of \
a Historical Value at Risk (VaR) model using evidence produced by the deterministic \
RiskLab engine.

AUTHORITY OF DETERMINISTIC OUTPUTS
- The deterministic RiskLab engine is authoritative for every quantitative value.
- You must call the registered tools whenever quantitative evidence is needed.
- You must never invent, estimate, guess, or approximate numerical metrics.
- You must never recompute risk statistics yourself. Do not calculate returns, VaR, \
Expected Shortfall, breach counts, breach rates, likelihood-ratio statistics, or \
p-values. Read them from tool results only.
- Do not output any number that was not returned by a tool.
- You decide which evidence you need; you do not produce the evidence.

INTERPRETING THE KUPIEC TEST
- Never claim the model is proven, correct, validated, or verified.
- A Kupiec non-rejection means only that unconditional coverage was not rejected at \
the selected significance level. It is not evidence that the model is correct.
- A Kupiec rejection means the observed breach frequency is statistically \
inconsistent with expected unconditional VaR coverage at the selected significance \
level.

LIMITATIONS YOU MUST RESPECT
- Statistical validation has limitations and cannot establish model correctness.
- The Kupiec unconditional coverage test does not test breach independence or \
breach clustering. Passing it says nothing about whether breaches arrive in bursts.
- Historical VaR depends on the historical sample being representative of future \
conditions.
- Expected Shortfall can be unstable when estimated from thin tails.

HOW TO ANSWER
Structure every assessment so these are clearly distinguished:
1. Observed result - the deterministic figures returned by tools.
2. Statistical interpretation - what those figures do and do not support.
3. Limitations - what the evidence cannot establish.
4. Recommended follow-up - the next diagnostic that would strengthen the assessment.

TOOL DISCIPLINE
- Inspect breach details or worst portfolio days when that evidence would materially \
improve the assessment, for example when judging breach severity or clustering.
- Do not request irrelevant tools just to appear agentic. Every call must have a \
reason tied to the question.
"""


class AgentError(RuntimeError):
    pass


class MaxStepsExceededError(AgentError):
    pass


def _coerce_arguments(name: str, arguments) -> dict:
    if arguments is None:
        return {}

    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Tool arguments for {name} are not valid JSON: {error}"
            ) from error

        if not isinstance(parsed, dict):
            raise ValueError(
                f"Tool arguments for {name} must decode to an object, "
                f"got {type(parsed).__name__}"
            )
        return parsed

    if not isinstance(arguments, dict):
        raise ValueError(
            f"Tool arguments for {name} must be an object, "
            f"got {type(arguments).__name__}"
        )

    return arguments


def _serialize_result(name: str, result) -> dict:
    # Fail loudly if a tool ever returns something the provider cannot receive.
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise AgentError(
            f"Tool {name} returned a result that is not JSON-serializable: {error}"
        ) from error

    return result


def build_messages(question: str) -> list[dict]:
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]


def run_validation_agent(
    question: str,
    provider: LLMProvider,
    max_steps: int = 6,
) -> dict:
    if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps <= 0:
        raise ValueError(f"max_steps must be a positive integer, got {max_steps!r}")

    messages = build_messages(question)
    tools = tool_schemas()

    trace = []
    evidence = []
    continuation_id = None
    tool_outputs = None
    steps = 0

    while steps < max_steps:
        steps += 1

        response = provider.respond(
            messages=messages,
            tools=tools,
            continuation_id=continuation_id,
            tool_outputs=tool_outputs,
        )
        continuation_id = response.continuation_id

        if not response.tool_calls:
            return {
                "answer": response.text,
                "tool_calls": trace,
                "evidence": evidence,
                "steps": int(steps),
            }

        tool_outputs = []
        for call in response.tool_calls:
            arguments = _coerce_arguments(call.name, call.arguments)
            result = _serialize_result(call.name, execute_tool(call.name, arguments))

            trace.append(
                {"step": int(steps), "tool": call.name, "arguments": arguments}
            )
            evidence.append({"tool": call.name, "result": result})
            tool_outputs.append(
                {
                    "call_id": call.call_id,
                    "name": call.name,
                    "output": json.dumps(result, allow_nan=False),
                }
            )

    raise MaxStepsExceededError(
        f"Validation agent stopped after {max_steps} steps without a final answer. "
        f"Tools executed: {[entry['tool'] for entry in trace]}"
    )
