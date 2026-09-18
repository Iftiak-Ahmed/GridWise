"""Deterministic validation layer between the LLM and the optimizer (Problem Statement Sec. 08).

LLM output is untrusted structured data. Every entry is checked here; anything that does not
satisfy the exact required shape is demoted to a safe `no_op` rather than passed through or
allowed to crash the service. This module never invents a new directive type and never lets
malformed numeric fields (non-finite, wrong sign, out-of-range) reach the optimizer.
"""
from __future__ import annotations

import math
from typing import Any

from app.config import DIRECTIVE_TYPES


def _is_finite_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _valid_hours(hours: Any) -> list[int] | None:
    if not isinstance(hours, list) or len(hours) == 0:
        return None
    if not all(isinstance(h, int) and not isinstance(h, bool) for h in hours):
        return None
    if any(h < 0 or h > 23 for h in hours):
        return None
    if len(set(hours)) != len(hours):
        return None
    if hours != sorted(hours):
        return None
    return hours


def _safe_no_op(note_index: int, reason: str) -> dict[str, Any]:
    return {
        "note_index": note_index,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": f"[guardrail: {reason}] treated as no_op",
    }


def _validate_structured_adjustment(
    directive_type: str, adjustment: Any, battery_capacity_kwh: float
) -> dict[str, Any] | None:
    if not isinstance(adjustment, dict):
        return None

    hours = _valid_hours(adjustment.get("hours"))
    if hours is None:
        return None

    if directive_type == "solar_reduction":
        factor = adjustment.get("factor")
        if not _is_finite_number(factor) or factor < 0 or factor > 1:
            return None
        return {"hours": hours, "factor": float(factor)}

    if directive_type == "minimum_battery_reserve":
        reserve = adjustment.get("minimum_energy_kwh")
        if not _is_finite_number(reserve) or reserve < 0 or reserve > battery_capacity_kwh:
            return None
        return {"hours": hours, "minimum_energy_kwh": float(reserve)}

    if directive_type == "no_charge_window":
        return {"hours": hours}

    if directive_type == "no_discharge_window":
        return {"hours": hours}

    if directive_type == "max_grid_window":
        cap = adjustment.get("max_grid_kwh")
        if not _is_finite_number(cap) or cap < 0:
            return None
        return {"hours": hours, "max_grid_kwh": float(cap)}

    return None


def validate_interpretations(
    operator_notes: list[str],
    raw_entries: list[dict[str, Any]],
    battery_capacity_kwh: float,
) -> list[dict[str, Any]]:
    """Coerces raw (untrusted) entries into exactly one safe, schema-valid entry per note.

    Guarantees:
    - Exactly one entry per note_index in 0..N-1, in ascending order.
    - no_op <=> applies is False and structured_adjustment is None.
    - Every other directive has applies True and a structured_adjustment matching its
      required shape exactly, with valid finite/ranged numeric values and clean hours.
    """
    n = len(operator_notes)
    by_index: dict[int, dict[str, Any]] = {}

    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        idx = raw.get("note_index")
        if not isinstance(idx, int) or isinstance(idx, bool) or idx < 0 or idx >= n:
            continue
        if idx in by_index:
            # Note mapping guardrail: each note may appear once. First valid occurrence wins.
            continue

        directive_type = raw.get("directive_type")
        applies = raw.get("applies")
        explanation = raw.get("explanation")
        if not isinstance(explanation, str) or not explanation.strip():
            explanation = "No explanation provided."

        if directive_type not in DIRECTIVE_TYPES:
            by_index[idx] = _safe_no_op(idx, "unsupported directive_type")
            continue

        if directive_type == "no_op":
            by_index[idx] = {
                "note_index": idx,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": explanation,
            }
            continue

        if applies is not True:
            by_index[idx] = _safe_no_op(idx, "non-no_op directive must have applies=true")
            continue

        adjustment = _validate_structured_adjustment(
            directive_type, raw.get("structured_adjustment"), battery_capacity_kwh
        )
        if adjustment is None:
            by_index[idx] = _safe_no_op(idx, "structured_adjustment failed validation")
            continue

        by_index[idx] = {
            "note_index": idx,
            "applies": True,
            "directive_type": directive_type,
            "structured_adjustment": adjustment,
            "explanation": explanation,
        }

    # Fill any missing note indices (LLM omitted them) with safe no_op.
    for idx in range(n):
        if idx not in by_index:
            by_index[idx] = _safe_no_op(idx, "missing from LLM output")

    return [by_index[i] for i in range(n)]
