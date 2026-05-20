# context.md §7.4: Applied to all LLM inputs (RFQ raw text, agent outputs).
# Prompt injection protection for Phase 2+.

from __future__ import annotations

import json
import re

from src.shared.domain.exceptions import ValidationError

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_INPUT_LENGTH = 8000

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"<\|.*?\|>", re.IGNORECASE | re.DOTALL),
    re.compile(r"\\n\\nHuman:", re.IGNORECASE),
    re.compile(r"\[INST\]", re.IGNORECASE),
    re.compile(r"###\s+Instruction", re.IGNORECASE),
]

_VALID_AGENT_ACTIONS = {"OFFER", "ACCEPT", "REJECT", "COUNTER"}

# Control characters except TAB (\t) and NEWLINE (\n)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# ── Public API ────────────────────────────────────────────────────────────────


def sanitize_llm_input(text: str) -> str:
    """
    Sanitize text before passing to an LLM.

    Steps:
    1. Check for injection patterns → raises ValidationError on match.
    2. Truncate to MAX_INPUT_LENGTH (hard truncation, not error).
    3. Strip null bytes and control chars (preserving \\t and \\n).

    Returns the cleaned text.
    context.md §7.4.
    """
    # 1. Injection pattern check (on full text, before truncation)
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            raise ValidationError(
                "Potential prompt injection detected in LLM input.",
                field="llm_input",
            )

    # 2. Hard-truncate to MAX_INPUT_LENGTH
    text = text[:MAX_INPUT_LENGTH]

    # 3. Strip control characters (preserve \t=0x09, \n=0x0a)
    text = _CONTROL_CHAR_RE.sub("", text)

    return text


def validate_agent_output(raw: str) -> dict:
    """
    Validate and parse LLM agent response.

    Expected JSON schema:
        {
          "action":    "OFFER" | "ACCEPT" | "REJECT" | "COUNTER",
          "price":     <positive number>,
          "reasoning": "<non-empty string>"
        }

    Raises ValidationError on any schema violation.
    Returns the validated dict.
    context.md §7.4.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # BUG-09 FIX: Attempt truncation recovery.
        # Groq's Llama model occasionally produces verbose reasoning that gets
        # cut off mid-JSON when LLM_MAX_TOKENS is too low, leaving a missing
        # closing brace. Strip trailing incomplete chars and try to close the object.
        truncated = raw.rstrip().rstrip(",")
        if not truncated.endswith("}"):
            truncated += "}"
        try:
            parsed = json.loads(truncated)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                f"Agent output is not valid JSON (recovery failed): {raw[:200]}",
                field="agent_output",
            ) from exc

    if not isinstance(parsed, dict):
        raise ValidationError(
            "Agent output must be a JSON object.",
            field="agent_output",
        )

    # Validate action
    action = parsed.get("action")
    if action not in _VALID_AGENT_ACTIONS:
        raise ValidationError(
            f"Invalid agent action '{action}'. "
            f"Must be one of: {sorted(_VALID_AGENT_ACTIONS)}.",
            field="action",
        )

    # Validate price
    price = parsed.get("price")
    if price is None:
        raise ValidationError("Agent output missing 'price' field.", field="price")
    try:
        price_float = float(price)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"Agent 'price' must be numeric; got {type(price).__name__}.",
            field="price",
        ) from exc
    if price_float <= 0:
        raise ValidationError(
            f"Agent 'price' must be positive; got {price_float}.",
            field="price",
        )

    # Validate reasoning
    reasoning = parsed.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise ValidationError(
            "Agent output 'reasoning' must be a non-empty string.",
            field="reasoning",
        )

    return {
        "action": action,
        "price": price_float,
        "reasoning": reasoning.strip(),
    }
