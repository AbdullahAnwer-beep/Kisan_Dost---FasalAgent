"""
Guardrails for Kisan Dost.

Input guardrail  -> rejects off-topic or unsafe requests before the main
                     agent spends a turn on them (e.g. human-medical
                     questions, requests unrelated to farming).
Output guardrail -> double-checks the FINAL reply never contains human
                     medical advice or unsafe pesticide-dosage language,
                     since farmers sometimes describe their own symptoms
                     by mistake instead of the crop's.
"""

import re
from agents import (
    Agent, Runner, RunContextWrapper, GuardrailFunctionOutput,
    input_guardrail, output_guardrail,
)
from pydantic import BaseModel

from .models import GuardrailCheck


def _input_text(user_input) -> str:
    """Normalize SDK string or message-list input for keyword checks."""
    if isinstance(user_input, str):
        return user_input
    if isinstance(user_input, list):
        parts = []
        for message in user_input:
            if isinstance(message, dict):
                content = message.get("content", "")
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):
                    parts.extend(
                        item.get("text", "") for item in content
                        if isinstance(item, dict) and isinstance(item.get("text"), str)
                    )
        return " ".join(parts)
    return str(user_input)

# Keywords that signal the question is about a HUMAN, not a crop/field.
HUMAN_MEDICAL_PATTERNS = [
    r"\bmy (chest|stomach|head|fever|body|child|baby|son|daughter)\b",
    r"\bi feel (sick|dizzy|unwell)\b",
    r"\bhuman (dose|dosage|medicine)\b",
    r"\bdoctor for me\b",
]

OFF_TOPIC_KEYWORDS = [
    "stock market", "cryptocurrency", "write my essay", "homework",
    "relationship advice", "political opinion", "election",
]

_topic_guard_agent = Agent(
    name="Topic Guardrail Agent",
    instructions=(
        "You check whether a message is a legitimate farming / agronomy question "
        "for Kisan Dost (crops, irrigation, sowing, harvest, fertilizer, pests, "
        "mandi prices, government farm schemes, weather for farming). "
        "Reply with is_allowed=false ONLY if the message is clearly unrelated to "
        "farming, or is asking for human medical advice, or asks for something "
        "unsafe/illegal. Otherwise is_allowed=true. Keep reason under 20 words."
    ),
    output_type=GuardrailCheck,
    model="gpt-4o-mini",
)


@input_guardrail
async def farming_topic_guardrail(
    ctx: RunContextWrapper, agent: Agent, user_input: str
) -> GuardrailFunctionOutput:
    """Fast keyword pass first (cheap, catches obvious cases), then a small
    LLM check for anything ambiguous."""
    lowered = _input_text(user_input).lower()

    for pattern in HUMAN_MEDICAL_PATTERNS:
        if re.search(pattern, lowered):
            return GuardrailFunctionOutput(
                output_info=GuardrailCheck(
                    is_allowed=False,
                    reason="This looks like a human medical question, not a crop question.",
                ),
                tripwire_triggered=True,
            )

    if any(kw in lowered for kw in OFF_TOPIC_KEYWORDS):
        return GuardrailFunctionOutput(
            output_info=GuardrailCheck(is_allowed=False, reason="Off-topic request, unrelated to farming."),
            tripwire_triggered=True,
        )

    result = await Runner.run(_topic_guard_agent, user_input, context=ctx.context)
    check: GuardrailCheck = result.final_output
    return GuardrailFunctionOutput(output_info=check, tripwire_triggered=not check.is_allowed)


UNSAFE_DOSAGE_PATTERN = re.compile(r"\b(\d{2,})\s*(ml|litre|liter|l)\b", re.IGNORECASE)
MEDICAL_LEAK_PATTERN = re.compile(
    r"\b(take|swallow|drink)\b.{0,15}\b(tablet|medicine|pill|syrup)\b", re.IGNORECASE
)


@output_guardrail
async def safety_output_guardrail(
    ctx: RunContextWrapper, agent: Agent, output
) -> GuardrailFunctionOutput:
    """Blocks replies that slip into human-medical advice, and flags any
    pesticide dosage that looks dangerously high for a per-acre spray."""
    text = str(output)

    if MEDICAL_LEAK_PATTERN.search(text):
        return GuardrailFunctionOutput(
            output_info=GuardrailCheck(is_allowed=False, reason="Reply contains human-medical advice."),
            tripwire_triggered=True,
        )

    for match in UNSAFE_DOSAGE_PATTERN.finditer(text):
        amount = int(match.group(1))
        if amount > 15:  # a per-acre pesticide spray should never call for >15L of concentrate
            return GuardrailFunctionOutput(
                output_info=GuardrailCheck(
                    is_allowed=False,
                    reason=f"Reply suggests {amount}{match.group(2)}, above the safe per-acre dosage ceiling.",
                ),
                tripwire_triggered=True,
            )

    return GuardrailFunctionOutput(
        output_info=GuardrailCheck(is_allowed=True, reason="Passed safety checks."),
        tripwire_triggered=False,
    )
