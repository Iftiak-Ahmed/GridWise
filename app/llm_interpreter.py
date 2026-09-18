"""Primary operator-note interpretation path: a language-capable generative model.

This module is the ONLY place that is allowed to decide what an operator note *means*.
Everything downstream (guardrails.py, optimizer.py) treats its output as untrusted
structured data (Problem Statement Sec. 08) and validates it before use.

Two hosted LLM providers are tried in order (Groq, then Gemini) so a rate limit or outage
on one still leaves a real language model on the interpretation path instead of dropping
straight to the deterministic heuristic. `interpret_notes` raises `LLMUnavailableError` only
if BOTH providers fail, so the caller can invoke the deterministic safety-net fallback
(fallback_interpreter.py) instead of crashing the request. That fallback exists purely for
total-outage robustness, never as a primary interpreter.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

import httpx

from app.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_TIMEOUT_SECONDS,
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_TIMEOUT_SECONDS,
)

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_GENERATE_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

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
    """Raised when every configured LLM provider call fails and could not be recovered."""


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


def _parse_interpretations(raw_text: str, provider: str) -> list[dict[str, Any]]:
    cleaned = _strip_fences(raw_text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMUnavailableError(f"{provider} returned non-JSON output: {exc}") from exc

    interpretations = parsed.get("interpretations")
    if not isinstance(interpretations, list):
        raise LLMUnavailableError(f"{provider} JSON payload missing 'interpretations' array")
    return interpretations


def _call_groq(operator_notes: list[str], battery_capacity_kwh: float) -> list[dict[str, Any]]:
    if not GROQ_API_KEY:
        raise LLMUnavailableError("GROQ_API_KEY is not configured")

    payload = {
        "model": GROQ_MODEL,
        "temperature": 0,
        "max_tokens": 1536,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(operator_notes, battery_capacity_kwh)},
        ],
    }

    try:
        response = httpx.post(
            GROQ_CHAT_COMPLETIONS_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=GROQ_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LLMUnavailableError(
            f"Groq API error: HTTP {exc.response.status_code} {exc.response.text[:200]}"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - any transport/timeout failure -> next provider
        raise LLMUnavailableError(f"Groq call failed: {exc.__class__.__name__}") from exc

    try:
        raw_text = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise LLMUnavailableError(f"Groq response missing expected content: {exc}") from exc

    return _parse_interpretations(raw_text, "Groq")


def _call_gemini(operator_notes: list[str], battery_capacity_kwh: float) -> list[dict[str, Any]]:
    if not GEMINI_API_KEY:
        raise LLMUnavailableError("GEMINI_API_KEY is not configured")

    user_message = _build_user_message(operator_notes, battery_capacity_kwh)
    payload = {
        "contents": [{"parts": [{"text": SYSTEM_PROMPT + "\n\n" + user_message}]}],
        "generationConfig": {
            "temperature": 0,
            "thinkingConfig": {"thinkingBudget": 0},
            "responseMimeType": "application/json",
        },
    }
    url = GEMINI_GENERATE_URL_TEMPLATE.format(model=GEMINI_MODEL)

    try:
        response = httpx.post(
            url,
            params={"key": GEMINI_API_KEY},
            json=payload,
            timeout=GEMINI_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LLMUnavailableError(
            f"Gemini API error: HTTP {exc.response.status_code} {exc.response.text[:200]}"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - any transport/timeout failure -> next provider
        raise LLMUnavailableError(f"Gemini call failed: {exc.__class__.__name__}") from exc

    try:
        raw_text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise LLMUnavailableError(f"Gemini response missing expected content: {exc}") from exc

    return _parse_interpretations(raw_text, "Gemini")


_PROVIDERS: list[Callable[[list[str], float], list[dict[str, Any]]]] = [_call_groq, _call_gemini]


def interpret_notes(operator_notes: list[str], battery_capacity_kwh: float) -> list[dict[str, Any]]:
    """Calls each configured LLM provider in order until one succeeds.

    Tries Groq first, then Gemini, so a rate limit or transient outage on one provider still
    leaves a real language model on the interpretation path. Raises LLMUnavailableError only
    if every provider call fails, so the caller can invoke the deterministic fallback.
    """
    errors: list[str] = []
    for call in _PROVIDERS:
        try:
            return call(operator_notes, battery_capacity_kwh)
        except LLMUnavailableError as exc:
            errors.append(str(exc))

    raise LLMUnavailableError("All LLM providers failed: " + " | ".join(errors))
