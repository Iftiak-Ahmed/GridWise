"""Adversarial paraphrase-robustness self-test.

The hidden judge set (Participant Guide Sec. 10) paraphrases the same underlying directive
with different wording, and explicitly warns teams not to hard-code public phrasing. This
script builds our OWN paraphrase stress-test so weaknesses in the interpretation prompt show
up before judging, not during it:

For every ground-truth-labeled operator note in samples/public_cases.json, it asks an LLM to
generate several differently-worded paraphrases that preserve every fact/number/time exactly,
then feeds each paraphrase through the REAL interpret_notes() -> guardrails pipeline and checks
the result still matches the published ground truth (directive_type, hours, and the relevant
numeric field, within tolerance).

This is robustness testing of our own prompt, not hard-coded phrase matching — the paraphrases
are generated fresh each run and never seen by the interpreter beforehand.

Requires GROQ_API_KEY (used both to generate paraphrases and, via interpret_notes, to
interpret them). Usage:
    python -m tests.run_paraphrase_robustness [--per-note N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from app import guardrails
from app.config import GROQ_API_KEY, GROQ_MODEL, NUMERIC_TOLERANCE
from app.llm_interpreter import LLMUnavailableError, interpret_notes

SAMPLES_PATH = Path(__file__).resolve().parent.parent / "samples" / "public_cases.json"

_NUMERIC_FIELD_BY_TYPE = {
    "solar_reduction": "factor",
    "minimum_battery_reserve": "minimum_energy_kwh",
    "max_grid_window": "max_grid_kwh",
}


def _generate_paraphrases(note: str, count: int) -> list[str]:
    prompt = (
        f"Reword the following operator note in {count} different ways. Preserve every fact, "
        "number, unit, and time reference EXACTLY (do not change times, percentages, or kWh "
        "values) — only change sentence structure and word choice. Include at least one "
        "version using 24-hour/military clock time if the original uses AM/PM, or vice versa. "
        'Respond with ONLY a JSON object: {"paraphrases": ["...", "...", ...]}\n\n'
        f"Original note: {note}"
    )
    payload = {
        "model": GROQ_MODEL,
        "temperature": 0.7,
        "max_tokens": 800,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}],
    }
    response = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    text = response.json()["choices"][0]["message"]["content"]
    data = json.loads(text)
    paraphrases = data.get("paraphrases", [])
    return [p for p in paraphrases if isinstance(p, str) and p.strip()][:count]


def _matches_ground_truth(got: dict, truth: dict) -> tuple[bool, str]:
    if got["directive_type"] != truth["directive_type"]:
        return False, f"directive_type {got['directive_type']!r} != {truth['directive_type']!r}"
    if not truth["applies"]:
        return got["applies"] is False, "expected no_op/applies=false"

    got_adj = got["structured_adjustment"] or {}
    truth_adj = truth["structured_adjustment"] or {}

    if got_adj.get("hours") != truth_adj.get("hours"):
        return False, f"hours {got_adj.get('hours')} != {truth_adj.get('hours')}"

    field = _NUMERIC_FIELD_BY_TYPE.get(truth["directive_type"])
    if field:
        got_val, truth_val = got_adj.get(field), truth_adj.get(field)
        if got_val is None or abs(got_val - truth_val) > max(NUMERIC_TOLERANCE, truth_val * 0.05):
            return False, f"{field} {got_val} != {truth_val}"

    return True, "ok"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-note", type=int, default=3, help="paraphrases to generate per note")
    args = parser.parse_args()

    if not GROQ_API_KEY:
        print("GROQ_API_KEY is not set — cannot generate or interpret paraphrases. Skipping.")
        return 0

    cases = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))["cases"]

    total = 0
    passed = 0
    for case in cases:
        capacity = case["input"]["battery"]["capacity_kwh"]
        for truth in case["expected_output"]["directive_interpretation"]:
            note = case["input"]["operator_notes"][truth["note_index"]]
            try:
                paraphrases = _generate_paraphrases(note, args.per_note)
            except Exception as exc:  # noqa: BLE001
                print(f"[{case['id']}] note {truth['note_index']}: paraphrase generation failed ({exc})")
                continue

            for para in paraphrases:
                total += 1
                try:
                    raw = interpret_notes([para], capacity)
                except LLMUnavailableError as exc:
                    print(f"[FAIL] {case['id']}#{truth['note_index']}: LLM unavailable ({exc})")
                    print(f"        paraphrase: {para!r}")
                    continue

                validated = guardrails.validate_interpretations([para], raw, capacity)[0]
                ok, reason = _matches_ground_truth(validated, truth)
                status = "PASS" if ok else "FAIL"
                if ok:
                    passed += 1
                else:
                    print(f"[{status}] {case['id']}#{truth['note_index']}: {reason}")
                    print(f"        original:   {note!r}")
                    print(f"        paraphrase: {para!r}")

    print(f"\n{passed}/{total} paraphrases resolved to the correct ground-truth directive.")
    return 0 if total > 0 and passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
