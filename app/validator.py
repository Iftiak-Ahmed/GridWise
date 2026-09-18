"""Independent replay validator (Problem Statement Sec. 09, 11.2-11.3).

Mirrors what the judge harness is described as doing: replay the returned hourly_plan
hour-by-hour against effective solar, battery bounds/rate-limits, energy balance, and
end-of-day neutrality, plus every applicable directive. Used both as an internal sanity
check before responding and by our own test suite against the public sample cases.

Returns a list of human-readable violation strings; an empty list means the plan is valid.
"""
from __future__ import annotations

from typing import Any

from app.config import NUMERIC_TOLERANCE as TOL
from app.optimizer import _effective_solar, _max_grid, _min_reserve, _no_charge_hours, _no_discharge_hours


def replay(hours_in: list[dict], battery: dict, directives: list[dict], plan: list[dict]) -> list[str]:
    violations: list[str] = []
    hours = sorted(hours_in, key=lambda h: h["hour"])

    plan_by_hour = {p["hour"]: p for p in plan}
    if sorted(plan_by_hour.keys()) != list(range(24)):
        violations.append("hourly_plan does not contain exactly 24 unique hours 0..23")
        return violations

    effective_solar = _effective_solar(hours, directives)
    no_charge = _no_charge_hours(directives)
    no_discharge = _no_discharge_hours(directives)
    min_reserve = _min_reserve(24, battery["minimum_energy_kwh"], directives)
    max_grid = _max_grid(24, directives)

    prev_energy = battery["initial_energy_kwh"]
    for h in range(24):
        p = plan_by_hour[h]
        demand = hours[h]["demand_kwh"]

        for field in ("grid_kwh", "solar_used_kwh", "battery_kwh", "battery_energy_after_kwh"):
            if p[field] < -TOL:
                violations.append(f"hour {h}: {field} is negative ({p[field]})")

        action = p["battery_action"]
        mag = p["battery_kwh"]
        if action == "idle" and mag > TOL:
            violations.append(f"hour {h}: battery_kwh must be 0 when idle, got {mag}")
        if action == "charge":
            if mag - TOL > battery["max_charge_kwh_per_hour"]:
                violations.append(f"hour {h}: charge {mag} exceeds max_charge_kwh_per_hour")
            if h in no_charge and mag > TOL:
                violations.append(f"hour {h}: charging occurred during a no_charge_window")
            expected_energy = prev_energy + mag
        elif action == "discharge":
            if mag - TOL > battery["max_discharge_kwh_per_hour"]:
                violations.append(f"hour {h}: discharge {mag} exceeds max_discharge_kwh_per_hour")
            if h in no_discharge and mag > TOL:
                violations.append(f"hour {h}: discharging occurred during a no_discharge_window")
            expected_energy = prev_energy - mag
        else:
            expected_energy = prev_energy

        if abs(expected_energy - p["battery_energy_after_kwh"]) > TOL:
            violations.append(
                f"hour {h}: battery_energy_after_kwh {p['battery_energy_after_kwh']} "
                f"inconsistent with battery_action/battery_kwh (expected {expected_energy})"
            )

        if p["battery_energy_after_kwh"] < min_reserve[h] - TOL:
            violations.append(f"hour {h}: battery_energy_after_kwh below required reserve {min_reserve[h]}")
        if p["battery_energy_after_kwh"] > battery["capacity_kwh"] + TOL:
            violations.append(f"hour {h}: battery_energy_after_kwh exceeds capacity_kwh")

        if p["solar_used_kwh"] > effective_solar[h] + TOL:
            violations.append(f"hour {h}: solar_used_kwh exceeds effective solar {effective_solar[h]}")

        if max_grid[h] is not None and p["grid_kwh"] > max_grid[h] + TOL:
            violations.append(f"hour {h}: grid_kwh exceeds max_grid_window cap {max_grid[h]}")

        balance_lhs = p["grid_kwh"] + p["solar_used_kwh"] + (mag if action == "discharge" else 0.0)
        balance_rhs = demand + (mag if action == "charge" else 0.0)
        if abs(balance_lhs - balance_rhs) > TOL:
            violations.append(f"hour {h}: energy balance violated ({balance_lhs} != {balance_rhs})")

        prev_energy = p["battery_energy_after_kwh"]

    if abs(prev_energy - battery["initial_energy_kwh"]) > TOL:
        violations.append(
            f"end-of-day battery energy {prev_energy} != initial_energy_kwh {battery['initial_energy_kwh']}"
        )

    return violations


def recompute_totals(plan: list[dict], hours_in: list[dict]) -> dict[str, float]:
    hours = sorted(hours_in, key=lambda h: h["hour"])
    tariff_by_hour = {h["hour"]: h["tariff_bdt_per_kwh"] for h in hours}
    total_grid = sum(p["grid_kwh"] for p in plan)
    total_cost = sum(p["grid_kwh"] * tariff_by_hour[p["hour"]] for p in plan)
    peak_grid = max(p["grid_kwh"] for p in plan)
    return {
        "total_grid_kwh": round(total_grid, 4),
        "total_cost_bdt": round(total_cost, 4),
        "peak_grid_kwh": round(peak_grid, 4),
    }
