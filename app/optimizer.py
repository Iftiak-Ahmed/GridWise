"""Deterministic 24-hour cost-minimizing optimizer (Problem Statement Sec. 05, 09).

Formulated as a linear program and solved exactly with CBC (via PuLP) — no ML, no
heuristics, fully reproducible given the same inputs. Directives are applied as hard
linear constraints per Sec. 5.3 before the objective (total grid cost) is minimized.
"""
from __future__ import annotations

from typing import Any

import pulp

_EPS = 1e-6
# Tiny regularization on battery cycling so the solver prefers the least battery movement
# among cost-equivalent solutions (avoids degenerate simultaneous charge+discharge and
# unnecessary idle-hour cycling). Small enough to never move recalculated cost by >0.01 BDT
# for any realistic tariff scale in this challenge.
_CYCLE_PENALTY = 1e-6


def _effective_solar(hours: list[dict], directives: list[dict]) -> list[float]:
    factors = [1.0] * 24
    for d in directives:
        if d["directive_type"] != "solar_reduction" or not d["applies"]:
            continue
        adj = d["structured_adjustment"]
        for h in adj["hours"]:
            factors[h] *= adj["factor"]
    return [hours[h]["solar_kwh"] * factors[h] for h in range(24)]


def _no_charge_hours(directives: list[dict]) -> set[int]:
    out: set[int] = set()
    for d in directives:
        if d["directive_type"] == "no_charge_window" and d["applies"]:
            out.update(d["structured_adjustment"]["hours"])
    return out


def _no_discharge_hours(directives: list[dict]) -> set[int]:
    out: set[int] = set()
    for d in directives:
        if d["directive_type"] == "no_discharge_window" and d["applies"]:
            out.update(d["structured_adjustment"]["hours"])
    return out


def _min_reserve(hours_count: int, base_min: float, directives: list[dict]) -> list[float]:
    reserve = [base_min] * hours_count
    for d in directives:
        if d["directive_type"] == "minimum_battery_reserve" and d["applies"]:
            adj = d["structured_adjustment"]
            for h in adj["hours"]:
                reserve[h] = max(reserve[h], adj["minimum_energy_kwh"])
    return reserve


def _max_grid(hours_count: int, directives: list[dict]) -> list[float | None]:
    cap: list[float | None] = [None] * hours_count
    for d in directives:
        if d["directive_type"] == "max_grid_window" and d["applies"]:
            adj = d["structured_adjustment"]
            for h in adj["hours"]:
                c = adj["max_grid_kwh"]
                cap[h] = c if cap[h] is None else min(cap[h], c)
    return cap


def _solve_lp(
    hours: list[dict],
    battery: dict,
    effective_solar: list[float],
    no_charge: set[int],
    no_discharge: set[int],
    min_reserve: list[float],
    max_grid: list[float | None],
) -> tuple[str, list[dict] | None]:
    prob = pulp.LpProblem("gridwise_optimize", pulp.LpMinimize)

    grid = [pulp.LpVariable(f"grid_{h}", lowBound=0, upBound=max_grid[h]) for h in range(24)]
    solar_used = [
        pulp.LpVariable(f"solar_used_{h}", lowBound=0, upBound=effective_solar[h]) for h in range(24)
    ]
    charge = [
        pulp.LpVariable(
            f"charge_{h}", lowBound=0, upBound=0 if h in no_charge else battery["max_charge_kwh_per_hour"]
        )
        for h in range(24)
    ]
    discharge = [
        pulp.LpVariable(
            f"discharge_{h}",
            lowBound=0,
            upBound=0 if h in no_discharge else battery["max_discharge_kwh_per_hour"],
        )
        for h in range(24)
    ]
    energy = [
        pulp.LpVariable(f"energy_{h}", lowBound=min_reserve[h], upBound=battery["capacity_kwh"])
        for h in range(24)
    ]

    tariffs = [hours[h]["tariff_bdt_per_kwh"] for h in range(24)]
    prob += pulp.lpSum(grid[h] * tariffs[h] for h in range(24)) + _CYCLE_PENALTY * pulp.lpSum(
        charge[h] + discharge[h] for h in range(24)
    )

    for h in range(24):
        prev_energy = battery["initial_energy_kwh"] if h == 0 else energy[h - 1]
        prob += energy[h] == prev_energy + charge[h] - discharge[h]
        demand = hours[h]["demand_kwh"]
        prob += grid[h] + solar_used[h] + discharge[h] == demand + charge[h]

    prob += energy[23] == battery["initial_energy_kwh"]

    status = prob.solve(pulp.PULP_CBC_CMD(msg=0))
    status_name = pulp.LpStatus[status]

    if status_name != "Optimal":
        return status_name, None

    plan = []
    for h in range(24):
        g = max(0.0, pulp.value(grid[h]) or 0.0)
        s = max(0.0, pulp.value(solar_used[h]) or 0.0)
        c = max(0.0, pulp.value(charge[h]) or 0.0)
        dch = max(0.0, pulp.value(discharge[h]) or 0.0)
        e = pulp.value(energy[h]) or 0.0

        # Net out any solver-noise simultaneous charge/discharge.
        net = c - dch
        if net > _EPS:
            action, mag = "charge", net
        elif net < -_EPS:
            action, mag = "discharge", -net
        else:
            action, mag = "idle", 0.0

        plan.append(
            {
                "hour": h,
                "grid_kwh": round(g, 4),
                "solar_used_kwh": round(s, 4),
                "battery_action": action,
                "battery_kwh": round(mag, 4),
                "battery_energy_after_kwh": round(e, 4),
            }
        )

    return status_name, plan


def solve(hours_in: list[dict], battery: dict, directives: list[dict]) -> dict[str, Any]:
    """Solves the LP. Returns dict with keys: plan, status, relaxed (bool), dropped (list[str]).

    If the fully-constrained problem is infeasible (only possible with malformed/adversarial
    hidden input, since organizer-valid scenarios are guaranteed feasible per Sec. 05.1), we
    progressively relax directive groups — least-authoritative first — rather than crash or
    return 500, per the robustness requirement in the Participant Guide.
    """
    hours = sorted(hours_in, key=lambda h: h["hour"])

    relax_order = ["max_grid_window", "minimum_battery_reserve", "no_discharge_window", "no_charge_window", "solar_reduction"]
    active_directives = list(directives)
    dropped: list[str] = []

    while True:
        effective_solar = _effective_solar(hours, active_directives)
        no_charge = _no_charge_hours(active_directives)
        no_discharge = _no_discharge_hours(active_directives)
        min_reserve = _min_reserve(24, battery["minimum_energy_kwh"], active_directives)
        max_grid = _max_grid(24, active_directives)

        status, plan = _solve_lp(
            hours, battery, effective_solar, no_charge, no_discharge, min_reserve, max_grid
        )

        if plan is not None:
            return {
                "plan": plan,
                "status": status,
                "relaxed": len(dropped) > 0,
                "dropped": dropped,
            }

        if not relax_order:
            return {"plan": None, "status": status, "relaxed": True, "dropped": dropped}

        drop_type = relax_order.pop(0)
        before = len(active_directives)
        active_directives = [d for d in active_directives if d["directive_type"] != drop_type]
        if len(active_directives) != before:
            dropped.append(drop_type)
        # If nothing was actually dropped (no directive of that type was active), keep trying
        # the next relax tier in the same loop iteration.
        if len(active_directives) == before and relax_order:
            continue
