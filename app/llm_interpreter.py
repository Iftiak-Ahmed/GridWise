"""Primary operator-note interpretation path: a language-capable generative model.

This module is the ONLY place that is allowed to decide what an operator note *means*.
Everything downstream (guardrails.py, optimizer.py) treats its output as untrusted
structured data (Problem Statement Sec. 08) and validates it before use.

If the provider call itself fails (network error, timeout, auth failure, rate limit),
`interpret_notes` raises `LLMUnavailableError` so the caller can invoke the deterministic
safety-net fallback (fallback_interpreter.py) instead of crashing the request. That
fallback exists purely for provider-outage robustness, never as the primary interpreter.
"""
from __future__ import annotations

import json
import re
from typing import Any

import anthropic

from app.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, LLM_TIMEOUT_SECONDS

SYSTEM_PROMPT = """You are the operator-note interpretation engine for GridWise, a campus \
energy scheduling system. You convert short natural-language operator notes into strict \
machine-checkable directives for a downstream optimizer. You do not do any math and you do \
not decide the final schedule; you only classify and extract structured fields.

Supported directive types (use exactly one per note, or "no_op" if the note does not affect \
today's 24-hour energy schedule):

- solar_reduction: usable solar is reduced during specific hours.
  structured_adjustment: {"hours": [int...], "factor": number}
  "factor" is the USABLE FRACTION THAT REMAINS, not the reduction amount.
  Example: "80% reduction" or "cut solar by 80%" -> factor = 0.2.
  Example: "solar drops to 20%" / "only one-fifth of normal output" -> factor = 0.2.

- minimum_battery_reserve: battery energy must stay at or above a level during specific hours.
  structured_adjustment: {"hours": [int...], "minimum_energy_kwh": number}
  If the note gives a percentage of capacity (e.g. "keep at least 50% of battery capacity"),
  convert it to an absolute kWh value using the battery capacity_kwh provided to you.

- no_charge_window: battery charging is unavailable during specific hours.
  structured_adjustment: {"hours": [int...]}

- no_discharge_window: battery discharging is unavailable during specific hours.
  structured_adjustment: {"hours": [int...]}

- max_grid_window: grid import may not exceed a stated amount during specific hours.
  structured_adjustment: {"hours": [int...], "max_grid_kwh": number}

- no_op: the note is a distractor / does not affect today's energy schedule (e.g. it talks \
about something unrelated to demand, solar, battery, or grid import for the current day).
  structured_adjustment: null

Hour convention: hours are whole-hour, 0-23, start-inclusive and end-exclusive. \
"1 PM to 3 PM" -> hours [13, 14] (NOT [13,14,15]). "6 PM until 9 PM" -> [18,19,20]. \
Always return hours as unique integers in ascending order.

Do not invent demand, solar, tariff, or battery parameters. Do not use any directive type \
other than the six listed above. Do not merge multiple notes into one entry.

Respond with ONLY a single JSON object (no markdown fences, no commentary) of this exact shape:
{"interpretations": [
  {"note_index": 0, "applies": true, "directive_type": "solar_reduction",
   "structured_adjustment": {"hours": [13,14], "factor": 0.2},
   "explanation": "short reason"},
  ...
]}
Return exactly one entry per input note, in note_index order, covering every note index \
from 0 to N-1 exactly once."""


class LLMUnavailableError(RuntimeError):
    """Raised when the LLM provider call fails and could not be recovered."""


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


def _build_user_message(operator_notes: list[str], battery_capacity_kwh: float) -> str:
    notes_block = "\n".join(f"{i}: {note}" for i, note in enumerate(operator_notes))
    return (
        f"Battery capacity_kwh for this scenario: {battery_capacity_kwh}\n\n"
        f"Operator notes ({len(operator_notes)} total):\n{notes_block}\n\n"
        "Return the JSON object described in the system prompt now."
    )


def interpret_notes(operator_notes: list[str], battery_capacity_kwh: float) -> list[dict[str, Any]]:
    """Calls the LLM once for all notes in a scenario and returns raw (untrusted) entries.

    Raises LLMUnavailableError on any provider-level failure. Raises ValueError if the
    provider responded but the payload could not be parsed as JSON at all (also treated
    by the caller as a reason to fall back, since we must never invent data ourselves).
    """
    if not ANTHROPIC_API_KEY:
        raise LLMUnavailableError("ANTHROPIC_API_KEY is not configured")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=LLM_TIMEOUT_SECONDS, max_retries=1)

    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1536,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": _build_user_message(operator_notes, battery_capacity_kwh)}
            ],
        )
    except anthropic.APIError as exc:
        raise LLMUnavailableError(f"Anthropic API error: {exc.__class__.__name__}") from exc
    except Exception as exc:  # noqa: BLE001 - any transport/timeout failure -> fallback path
        raise LLMUnavailableError(f"LLM call failed: {exc.__class__.__name__}") from exc

    raw_text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )
    cleaned = _strip_fences(raw_text)

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMUnavailableError(f"LLM returned non-JSON output: {exc}") from exc

    interpretations = payload.get("interpretations")
    if not isinstance(interpretations, list):
        raise LLMUnavailableError("LLM JSON payload missing 'interpretations' array")

    return interpretations
