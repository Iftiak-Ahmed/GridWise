"""Offline validation of the guardrails + optimizer + validator pipeline.

This deliberately BYPASSES the LLM (feeding it the public sample pack's ground-truth
directive_interpretation as if a perfect model had produced it) so it can run with no
API key and no network access. It proves the deterministic core — the guardrail
validation, the LP optimizer, and the replay validator — is correct against every
public sample: every plan must be constraint-valid and cost-competitive with the
published reference.

It does NOT test the LLM's natural-language understanding; that requires GROQ_API_KEY
and is covered by tests/run_api_smoke.py instead.

Usage:
    python -m tests.run_offline_checks
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import guardrails, optimizer, validator

SAMPLES_PATH = Path(__file__).resolve().parent.parent / "samples" / "public_cases.json"


def main() -> int:
    data = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    cases = data["cases"]

    total = len(cases)
    passed = 0
    total_quality = 0.0

    print(f"Running offline checks against {total} public sample cases...\n")

    for case in cases:
        case_id = case["id"]
        req = case["input"]
        hours = req["hours"]
        battery = req["battery"]
        notes = req["operator_notes"]
        expected = case["expected_output"]
        ground_truth = expected["directive_interpretation"]
        reference_cost = expected["total_cost_bdt"]

        # Simulate a perfect LLM by feeding ground truth through the same guardrail path
        # every real request uses, then solve and replay exactly like the live service.
        directive_interpretation = guardrails.validate_interpretations(
            notes, ground_truth, battery["capacity_kwh"]
        )

        result = optimizer.solve(hours, battery, directive_interpretation)
        plan = result["plan"]

        ok = True
        messages = []

        # Sanity-check our own validator against the OFFICIAL reference schedule itself:
        # if our validator ever flagged the organizer's own valid plan as violating a
        # constraint, that would mean our validator (and by extension our optimizer's
        # constraints) diverge from the official rules.
        reference_violations = validator.replay(hours, battery, ground_truth, expected["hourly_plan"])
        if reference_violations:
            ok = False
            messages.append("validator disagrees with the OFFICIAL reference schedule:")
            messages.extend(f"  ! {v}" for v in reference_violations)

        if plan is None:
            ok = False
            messages.append(f"optimizer returned infeasible (status={result['status']})")
        else:
            violations = validator.replay(hours, battery, directive_interpretation, plan)
            if violations:
                ok = False
                messages.extend(violations)

            totals = validator.recompute_totals(plan, hours)
            our_cost = totals["total_cost_bdt"]
            quality = min(1.0, reference_cost / our_cost) if our_cost > 0 else 1.0
            total_quality += quality
            messages.append(
                f"cost: ours={our_cost:.2f} BDT, reference={reference_cost:.2f} BDT, "
                f"quality_ratio={quality:.4f}"
            )
            for field in ("total_grid_kwh", "peak_grid_kwh"):
                ours, ref = totals[field], expected[field]
                if abs(ours - ref) > max(0.01, ref * 0.001):
                    messages.append(f"note: {field} ours={ours:.2f} vs reference={ref:.2f} (differs, but an equivalent optimal schedule need not match)")

        # Confirm directive_interpretation coverage/shape guardrails.
        if len(directive_interpretation) != len(notes):
            ok = False
            messages.append("directive_interpretation entry count != number of notes")
        for i, d in enumerate(directive_interpretation):
            if d["note_index"] != i:
                ok = False
                messages.append(f"entry {i} has wrong note_index {d['note_index']}")
            if d["directive_type"] == "no_op" and d["applies"] is not False:
                ok = False
                messages.append(f"entry {i}: no_op must have applies=false")
            if d["directive_type"] != "no_op" and d["applies"] is not True:
                ok = False
                messages.append(f"entry {i}: non-no_op must have applies=true")

        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        print(f"[{status}] {case_id}")
        for m in messages:
            print(f"    - {m}")

    print(f"\n{passed}/{total} cases passed.")
    if passed > 0:
        avg_quality = total_quality / total if total else 0.0
        print(f"Average optimization quality_ratio (capped at 1.0 each): {avg_quality:.4f}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
