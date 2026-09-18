"""Deterministic safety-net interpreter.

USED ONLY when the LLM provider call itself fails (network error, timeout, missing/invalid
API key, rate limit, malformed non-JSON output). It is a crude keyword/regex heuristic and
is NOT a substitute for the language model — the LLM Requirement (Problem Statement Sec. 02,
Participant Guide Sec. 04/09) is satisfied by app/llm_interpreter.py, which is always tried
first on every request. This module exists solely so that a provider outage degrades to a
safe, non-crashing response (Participant Guide Sec. 08, "Robustness") instead of a 5xx.

Every entry produced here is clearly labeled in `explanation` so it is auditable in logs
and in the response itself.
"""
from __future__ import annotations

from typing import Any

from app.time_utils import extract_hour_window, extract_kwh, extract_percentage

_FALLBACK_TAG = "[fallback-heuristic: LLM unavailable] "


def _percent_of_capacity(text: str, capacity_kwh: float) -> float | None:
    pct = extract_percentage(text)
    if pct is None:
        return None
    return round(pct * capacity_kwh, 4)


def interpret_notes_fallback(
    operator_notes: list[str], battery_capacity_kwh: float
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for idx, note in enumerate(operator_notes):
        lower = note.lower()
        hours = extract_hour_window(note)

        entry: dict[str, Any] | None = None

        if hours is not None and any(
            kw in lower for kw in ("solar", "pv", "panel", "sunlight", "irradiance")
        ):
            pct = extract_percentage(note)
            if pct is not None:
                # Heuristic: "reduction of X%" implies remaining factor 1-X; "drop to X%" /
                # "output at X%" implies remaining factor X. We cannot reliably disambiguate
                # with regex, so prefer the "reduction" reading only when the word appears.
                if any(kw in lower for kw in ("reduction", "reduce", "cut", "less")):
                    factor = round(1.0 - pct, 4)
                else:
                    factor = round(pct, 4)
                factor = max(0.0, min(1.0, factor))
                entry = {
                    "note_index": idx,
                    "applies": True,
                    "directive_type": "solar_reduction",
                    "structured_adjustment": {"hours": hours, "factor": factor},
                    "explanation": _FALLBACK_TAG + "solar-related keyword + percentage detected",
                }

        elif hours is not None and "charg" in lower and "discharg" not in lower and any(
            kw in lower for kw in ("not charge", "no charg", "unavailable", "disabled", "isolated", "cannot charge")
        ):
            entry = {
                "note_index": idx,
                "applies": True,
                "directive_type": "no_charge_window",
                "structured_adjustment": {"hours": hours},
                "explanation": _FALLBACK_TAG + "charging-outage keyword detected",
            }

        elif hours is not None and "discharg" in lower and any(
            kw in lower for kw in ("not discharge", "no discharg", "unavailable", "disabled", "cannot discharge", "must not discharge")
        ):
            entry = {
                "note_index": idx,
                "applies": True,
                "directive_type": "no_discharge_window",
                "structured_adjustment": {"hours": hours},
                "explanation": _FALLBACK_TAG + "discharge-outage keyword detected",
            }

        elif hours is not None and any(
            kw in lower for kw in ("reserve", "keep at least", "remain in the battery", "must remain")
        ):
            kwh = extract_kwh(note) or _percent_of_capacity(note, battery_capacity_kwh)
            if kwh is not None:
                entry = {
                    "note_index": idx,
                    "applies": True,
                    "directive_type": "minimum_battery_reserve",
                    "structured_adjustment": {"hours": hours, "minimum_energy_kwh": kwh},
                    "explanation": _FALLBACK_TAG + "reserve keyword + kWh/percentage detected",
                }

        elif hours is not None and any(
            kw in lower for kw in ("grid import", "grid intake", "must not exceed", "feeder", "transformer limit", "not exceed")
        ):
            kwh = extract_kwh(note)
            if kwh is not None:
                entry = {
                    "note_index": idx,
                    "applies": True,
                    "directive_type": "max_grid_window",
                    "structured_adjustment": {"hours": hours, "max_grid_kwh": kwh},
                    "explanation": _FALLBACK_TAG + "grid-cap keyword + kWh detected",
                }

        if entry is None:
            entry = {
                "note_index": idx,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": _FALLBACK_TAG + "no confident heuristic match; treated as no_op",
            }

        results.append(entry)

    return results
